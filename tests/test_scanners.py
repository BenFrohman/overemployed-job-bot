# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Scanner tests against recorded-shape API responses; no live network."""
import asyncio


import httpx  # noqa: E402
import pytest  # noqa: E402

from app import scanners, scheduler  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models import JobListing  # noqa: E402
from sqlalchemy import select  # noqa: E402

FIXTURES = {
    "remotive.com": {"jobs": [
        {"id": 101, "url": "https://remotive.com/remote-jobs/x/101", "title": "AI Tutor &amp; Math Expert",
         "company_name": "Acme", "candidate_required_location": "Worldwide", "description": "<p>Teach</p>"},
        {"id": 102, "url": "https://remotive.com/remote-jobs/x/102", "title": "Senior Backend Engineer",
         "company_name": "Acme", "candidate_required_location": "USA", "description": "Write code"}]},
    "remoteok.com": [
        {"legal": "API terms: link back to Remote OK and mention it as a source."},
        {"id": "201", "slug": "math-tutor-201", "position": "Math Tutor", "company": "Globex",
         "location": "", "url": "https://remoteok.com/remote-jobs/math-tutor-201", "description": "Remote"}],
    "www.arbeitnow.com": {"data": [
        {"slug": "physics-tutor-301", "company_name": "Initech", "title": "Physics Tutor", "description": "x",
         "remote": True, "url": "https://www.arbeitnow.com/jobs/301", "location": "Berlin"},
        {"slug": "physics-tutor-301", "company_name": "Initech", "title": "Physics Tutor", "description": "dup",
         "remote": True, "url": "https://www.arbeitnow.com/jobs/301", "location": "Berlin"}]},
    "boards-api.greenhouse.io": {"jobs": [
        {"id": 401, "title": "Research Scientist, Alignment", "absolute_url": "https://boards.greenhouse.io/acme/401",
         "location": {"name": "Remote - US"}, "content": "&lt;p&gt;Study&lt;/p&gt;"}]},
    "api.lever.co": [
        {"id": "abc-501", "text": "Curriculum Designer", "hostedUrl": "https://jobs.lever.co/acme/abc-501",
         "categories": {"location": "New York"}, "workplaceType": "remote", "descriptionPlain": "Design"}],
    "api.ashbyhq.com": {"jobs": [
        {"id": "601", "title": "Policy Researcher", "location": "London", "isRemote": True, "isListed": True,
         "jobUrl": "https://jobs.ashbyhq.com/acme/601", "descriptionPlain": "Policy"},
        {"id": "602", "title": "Hidden", "location": "London", "isListed": False}]},
}


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["user-agent"].startswith("overemployed-job-bot/")
    if request.url.host == "broken.example":
        raise httpx.ConnectTimeout("timeout", request=request)
    body = FIXTURES.get(request.url.host)
    return httpx.Response(200, json=body) if body is not None else httpx.Response(404)


@pytest.fixture(autouse=True)
def mock_http(monkeypatch):
    s = get_settings()
    real = httpx.AsyncClient

    def client():
        return real(transport=httpx.MockTransport(_handler), timeout=s.scan_timeout_seconds,
                    headers={"User-Agent": s.scanner_user_agent})
    monkeypatch.setattr(scanners, "_client", client)
    monkeypatch.setattr(s, "scanners_enabled", "remotive,remoteok,arbeitnow,greenhouse,lever,ashby")
    monkeypatch.setattr(s, "greenhouse_boards", "acme")
    monkeypatch.setattr(s, "lever_companies", "acme")
    monkeypatch.setattr(s, "ashby_boards", "acme")
    scheduler.SCANNERS.clear()
    yield
    scheduler.SCANNERS.clear()


def test_normalization():
    r = asyncio.run(scanners.fetch_remotive())
    assert r[0].title == "AI Tutor & Math Expert" and r[0].description == "Teach" and r[0].remote
    ok = asyncio.run(scanners.fetch_remoteok())
    assert [j.external_id for j in ok] == ["201"] and ok[0].url.startswith("https://remoteok.com/")
    gh = asyncio.run(scanners.fetch_greenhouse("acme"))
    assert gh[0].source == "greenhouse:acme" and gh[0].remote and gh[0].description == "Study"
    lv = asyncio.run(scanners.fetch_lever("acme"))
    assert lv[0].remote and lv[0].location == "New York"
    ab = asyncio.run(scanners.fetch_ashby("acme"))
    assert [j.external_id for j in ab] == ["601"]


def test_enabled_setting(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scanners_enabled", "remotive,lever")
    names = [f.__name__ for f in scanners.build_scanners()]
    assert names == ["fetch_remotive", "fetch_lever[acme]"]
    monkeypatch.setattr(s, "scanners_enabled", "")
    assert scanners.build_scanners() == []


def test_cycle_filters_dedupes_and_isolates_failures():
    async def broken():
        return await scanners._get_json("https://broken.example/api")

    async def go():
        await init_db()
        scheduler.register_enabled_scanners()
        scheduler.register_scanner(broken)
        first = await scheduler.run_scan_cycle()
        second = await scheduler.run_scan_cycle()
        async with AsyncSessionLocal() as db:
            titles = sorted((await db.execute(select(JobListing.title).where(JobListing.source != "t"))).scalars())
        return first, second, titles

    first, second, titles = asyncio.run(go())
    # backend engineer filtered out by looks_applicable; arbeitnow duplicate dropped; broken source isolated
    assert titles == sorted(["AI Tutor & Math Expert", "Math Tutor", "Physics Tutor",
                             "Research Scientist, Alignment", "Curriculum Designer", "Policy Researcher"])
    assert first == 6 and second == 0
