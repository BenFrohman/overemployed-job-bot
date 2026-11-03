# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Scanner tests against recorded-shape API responses; no live network."""
import asyncio


import httpx  # noqa: E402
import pytest  # noqa: E402

from app import scanners, scheduler  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models import JobListing  # noqa: E402
from app.polite import PoliteClient  # noqa: E402
from app.registry import Company  # noqa: E402
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


FIXTURES.update({
    "apply.workable.com": {"name": "Inkomoko", "jobs": [
        {"title": "Climate Finance Officer", "shortcode": "W1", "url": "https://apply.workable.com/j/W1",
         "telecommuting": "True", "city": "Kigali", "country": "Rwanda", "description": "<p>Clean energy loans</p>"}]},
    "api.smartrecruiters.com": {"totalFound": 1, "content": [
        {"id": "SR1", "name": "Health Data Analyst", "company": {"name": "Visa"},
         "location": {"city": "Nairobi", "country": "ke", "remote": False},
         "function": {"label": "Analytics"}, "industry": {"label": "Healthcare"}}]},
    "acme.recruitee.com": {"offers": [
        {"id": 77, "title": "Teacher Success Lead", "location": "Amsterdam", "remote": True,
         "careers_url": "https://acme.recruitee.com/o/teacher", "description": "Help schools",
         "requirements": "Empathy", "salary": {"min": "60000", "max": "70000", "currency": "EUR", "period": "year"}}]},
    "hn.algolia.com": None,  # handled by path below
})

HN_SEARCH = {"hits": [{"title": "Ask HN: Who is hiring? (November 2026)", "objectID": "999"}]}
HN_ITEM = {"id": 999, "children": [
    {"id": 1001, "author": "a", "text": "GiveWell | Research Analyst | Remote (US) | $95k-$120k<p>Find the best charities."},
    {"id": 1002, "author": "b", "text": "Just a question, no job here"},
    {"id": 1003, "author": None, "text": None}]}


def _handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["user-agent"].startswith("overemployed-job-bot/")
    if request.url.host == "broken.example":
        raise httpx.ConnectTimeout("timeout", request=request)
    if request.url.host == "hn.algolia.com":
        return httpx.Response(200, json=HN_ITEM if "/items/" in request.url.path else HN_SEARCH)
    body = FIXTURES.get(request.url.host)
    return httpx.Response(200, json=body) if body is not None else httpx.Response(404)


ACME = {a: Company(a, "acme", "Acme Org", sector="Education") for a in
        ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee")}


async def _nosleep(_):
    return None


def _fresh_client():
    s = get_settings()
    scanners.set_client(PoliteClient(user_agent=s.scanner_user_agent, timeout=1, min_interval=0, retries=1,
                                      backoff=0, transport=httpx.MockTransport(_handler), sleep=_nosleep))


@pytest.fixture(autouse=True)
def mock_http(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scanners_enabled", ",".join(sorted(scanners.SOURCES)))
    monkeypatch.setattr(s, "catalog_filter", "all")
    monkeypatch.setattr(scanners, "registry", lambda: tuple(ACME.values()))
    scheduler.SCANNERS.clear()
    yield
    scheduler.SCANNERS.clear()
    scanners.set_client(None)


def run(coro_fn):
    async def go():
        _fresh_client()
        try:
            return await coro_fn()
        finally:
            await scanners.get_client().aclose()
    return asyncio.run(go())


def test_normalization():
    async def go():
        return [await scanners.fetch_remotive(), await scanners.fetch_remoteok(),
                await scanners.fetch_greenhouse(ACME["greenhouse"]), await scanners.fetch_lever(ACME["lever"]),
                await scanners.fetch_ashby(ACME["ashby"]), await scanners.fetch_workable(ACME["workable"]),
                await scanners.fetch_smartrecruiters(ACME["smartrecruiters"]),
                await scanners.fetch_recruitee(ACME["recruitee"]), await scanners.fetch_hn()]
    r, ok, gh, lv, ab, wk, sr, rc, hn = run(go)
    assert r[0].title == "AI Tutor & Math Expert" and r[0].description == "Teach" and r[0].remote
    assert [j.external_id for j in ok] == ["201"] and ok[0].url.startswith("https://remoteok.com/")
    assert gh[0].source == "greenhouse:acme" and gh[0].remote and gh[0].description == "Study"
    assert gh[0].company == "Acme Org" and gh[0].sector == "Education"
    assert lv[0].remote and lv[0].location == "New York"
    assert [j.external_id for j in ab] == ["601"]
    assert wk[0].remote and wk[0].location == "Kigali, Rwanda" and wk[0].url.endswith("/W1")
    assert sr[0].url == "https://jobs.smartrecruiters.com/acme/SR1" and not sr[0].remote
    assert rc[0].remote and "60,000–70,000 EUR year" in rc[0].description
    assert [(j.company, j.title, j.remote) for j in hn] == [("GiveWell", "Research Analyst", True)]
    assert hn[0].url == "https://news.ycombinator.com/item?id=1001"


def test_enabled_setting_and_rotation(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scanners_enabled", "remotive,lever")
    monkeypatch.setattr(s, "lever_companies", "extra-co")
    names = [f.__name__ for f in scanners.build_scanners()[0]]
    assert names == ["fetch_remotive", "lever[acme]", "lever[extra-co]"]
    monkeypatch.setattr(s, "use_company_registry", False)
    assert [f.__name__ for f in scanners.build_scanners()[0]] == ["fetch_remotive", "lever[extra-co]"]
    monkeypatch.setattr(s, "scanners_enabled", "")
    assert scanners.build_scanners()[0] == []
    # rotation wraps and spreads a sweep over cycles
    assert scanners.rotate([1, 2, 3, 4, 5], 0, 2) == ([1, 2], 2)
    assert scanners.rotate([1, 2, 3, 4, 5], 4, 2) == ([5, 1], 1)
    assert scanners.rotate([1, 2], 1, 5) == ([1, 2], 0)


def test_cycle_dedupes_isolates_failures_and_rotates(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "boards_per_cycle", 3)

    async def broken():
        return await scanners.get_client().get_json("https://broken.example/api")

    async def go():
        await init_db()
        first = await scheduler.run_scan_cycle()   # feeds + boards 0..2 (ashby, greenhouse, lever)
        second = await scheduler.run_scan_cycle()  # feeds (all dupes) + boards 3..5
        third = await scheduler.run_scan_cycle()   # wrapped: nothing new
        scheduler.register_scanner(broken)
        scheduler.register_scanner(scanners.fetch_remotive)
        fourth = await scheduler.run_scan_cycle()  # broken source must not stop remotive
        async with AsyncSessionLocal() as db:
            titles = sorted((await db.execute(select(JobListing.title))).scalars())
        return first, second, third, fourth, titles

    first, second, third, fourth, titles = run(go)
    # arbeitnow duplicate and the unlisted Ashby job are dropped; catalog_filter=all keeps engineering roles
    assert titles == sorted(["AI Tutor & Math Expert", "Senior Backend Engineer", "Math Tutor", "Physics Tutor",
                             "Research Analyst", "Research Scientist, Alignment", "Curriculum Designer",
                             "Policy Researcher", "Climate Finance Officer", "Health Data Analyst",
                             "Teacher Success Lead"])
    assert (first, second, third, fourth) == (8, 3, 0, 0)


def test_legacy_applicable_filter(monkeypatch):
    monkeypatch.setattr(get_settings(), "catalog_filter", "applicable")

    async def go():
        await init_db()
        return await scheduler.store_jobs(await scanners.fetch_remotive())
    assert run(go) == 1  # the backend engineer role is filtered out
