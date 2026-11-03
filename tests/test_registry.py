# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Company registry + refresher validation logic. Mocked HTTP only."""
import asyncio
import importlib.util
import json
from pathlib import Path

import httpx

from app.polite import PoliteClient
from app.registry import ATS, REGISTRY_PATH, is_alive, load_registry, probe_url, valid_slug

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("refresh_companies", ROOT / "scripts" / "refresh_companies.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def test_committed_registry_is_well_formed():
    doc = json.loads(REGISTRY_PATH.read_text())
    companies = load_registry()
    assert len(companies) == doc["total"] == len(doc["companies"]) > 0
    assert {c.ats for c in companies} <= set(ATS)
    assert len({(c.ats, c.slug.lower()) for c in companies}) == len(companies)  # no duplicates
    assert all(valid_slug(c.slug) for c in companies)
    assert {s["license"] for s in doc["seeds"]} <= {"CC-BY-4.0", "MIT"}  # only openly licensed seeds
    assert sum(doc["counts"].values()) == doc["total"]


def test_liveness_rules():
    assert is_alive("greenhouse", {"name": "Acme"}) and not is_alive("greenhouse", {})
    assert is_alive("lever", []) and is_alive("ashby", {"jobs": []})
    # SmartRecruiters answers 200/empty even for unknown companies, so empty is not proof
    assert not is_alive("smartrecruiters", {"totalFound": 0, "content": []})
    assert is_alive("smartrecruiters", {"totalFound": 2, "content": [{}]})
    assert probe_url("recruitee", "acme") == "https://acme.recruitee.com/api/offers/"
    assert not valid_slug("../etc") and not valid_slug("") and valid_slug("Acme-Co.io")


def test_validate_drops_dead_and_keeps_known_on_transient_error():
    def handler(req):
        if "alive" in str(req.url):
            return httpx.Response(200, json={"name": "Alive Inc", "jobs": []})
        if "flaky" in str(req.url):
            return httpx.Response(503)
        return httpx.Response(404)

    async def nosleep(_):
        return None

    cands = [{"ats": "greenhouse", "slug": "alive", "name": "", "sources": {"x"}},
             {"ats": "greenhouse", "slug": "dead", "name": "", "sources": {"x"}},
             {"ats": "lever", "slug": "flaky", "name": "", "sources": {"x"}, "known": True}]

    async def go():
        async with PoliteClient(user_agent="t", transport=httpx.MockTransport(handler), min_interval=0,
                                retries=1, sleep=nosleep) as c:
            return await refresh.validate(c, cands)
    alive, errored, stats = asyncio.run(go())
    assert [e["slug"] for e in alive] == ["alive"] and alive[0]["name"] == "Alive Inc"
    assert [e["slug"] for e in errored] == ["flaky"] and stats["dead"] == 1
