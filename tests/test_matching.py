# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Purpose matching: ranking, explanations, feedback, endpoints and per-user isolation."""
import asyncio

from fastapi.testclient import TestClient

from app.database import AsyncSessionLocal
from app.main import app
from app.matching import BM25, JobDoc, Profile, parse_salary, rank, tokenize
from app.models import JobListing

JOBS = [
    JobDoc(1, "Senior Python Engineer", "SolarGrid", "Remote", "Build Python data pipelines for solar energy "
           "and decarbonization. $150k-$180k", remote=True, sector="Climate"),
    JobDoc(2, "Python Developer", "AdTech Inc", "Remote", "Python services to optimize ad clicks. $160,000",
           remote=True),
    JobDoc(3, "Nurse", "City Hospital", "Chicago", "Patient care", remote=False, sector="Healthcare"),
    JobDoc(4, "Data Engineer", "OpenSchools", "Remote", "Python and SQL for student learning outcomes. $90k",
           remote=True, sector="Education"),
]
PROFILE = Profile(skills="python, sql, data pipelines", causes="climate", values="transparency",
                  desired_impact="cut carbon emissions", remote_preference="remote", comp_floor=120000)


def test_bm25_and_salary():
    docs = [tokenize(t) for t in ["python python data", "nursing care", "data"]]
    bm = BM25(docs)
    assert bm.score(["python"], 0) > 0 == bm.score(["python"], 1)
    assert parse_salary("Pay $150k-$180k") == (150000, 180000)
    assert parse_salary("$160,000 per year") == (160000, 160000)
    assert parse_salary("no pay info") is None


def test_rank_purpose_first_with_explanations():
    ms = rank(PROFILE, JOBS)
    ids = [m.job.id for m in ms]
    assert 3 not in ids  # onsite job filtered for a remote-only profile
    assert ids[0] == 1  # skills + mission + pay
    top = ms[0]
    assert "python" in top.why.lower() and "climate" in top.why.lower()
    assert set(top.parts) >= {"skills", "mission", "preferences"}
    low = next(m for m in ms if m.job.id == 4)
    assert "below" in low.why.lower()  # honest about the pay floor


def test_feedback_tunes_ranking():
    base = {m.job.id: m.score for m in rank(PROFILE, JOBS)}
    ms = rank(PROFILE, [j for j in JOBS if j.id != 1], saved=[JOBS[0]], dismissed=[JOBS[1]], dismissed_ids={2})
    assert 2 not in [m.job.id for m in ms]
    assert next(m for m in ms if m.job.id == 4).score >= base[4] - 1e-9


def _add_jobs():
    async def go():
        async with AsyncSessionLocal() as db:
            rows = [JobListing(source="t", external_id=str(j.id), title=j.title, company=j.company,
                               location=j.location, description=j.description, remote=j.remote, sector=j.sector)
                    for j in JOBS]
            db.add_all(rows)
            await db.commit()
            return [r.id for r in rows]
    return asyncio.run(go())


def test_endpoints_and_isolation():
    with TestClient(app) as a, TestClient(app) as b:
        assert a.post("/api/signup", json={"email": "a@x.io", "password": "password1"}).status_code == 201
        assert b.post("/api/signup", json={"email": "b@x.io", "password": "password2"}).status_code == 201
        ids = _add_jobs()
        body = {"skills": "python, sql, data pipelines", "causes": "climate", "values": "transparency",
                "desired_impact": "cut carbon emissions", "remote_preference": "remote", "comp_floor": 120000}
        assert a.put("/api/profile", json=body).json()["causes"] == "climate"
        assert a.put("/api/profile", json={**body, "remote_preference": "moon"}).status_code == 422
        assert b.get("/api/profile").json()["skills"] == ""  # b never sees a's profile
        res = a.get("/api/matches").json()
        assert res["engine"] == "bm25" and res["profile_complete"]
        assert res["matches"][0]["job"]["title"] == "Senior Python Engineer"
        assert res["matches"][0]["why"]
        top, other = res["matches"][0]["job"]["id"], res["matches"][1]["job"]["id"]
        assert a.post(f"/api/matches/{other}/feedback", json={"action": "dismiss"}).status_code == 200
        assert a.post(f"/api/matches/{top}/feedback", json={"action": "save"}).status_code == 200
        after = [m["job"]["id"] for m in a.get("/api/matches").json()["matches"]]
        assert other not in after and top not in after  # saved moves to applications; dismissed hidden
        assert [x["job_id"] for x in a.get("/api/applications").json()] == [top]
        assert other in [m["job"]["id"] for m in b.get("/api/matches").json()["matches"]]  # b unaffected
        assert b.get("/api/applications").json() == []
        assert a.post(f"/api/matches/{other}/feedback", json={"action": "clear"}).status_code == 200
        assert other in [m["job"]["id"] for m in a.get("/api/matches").json()["matches"]]
        assert a.post("/api/matches/99999/feedback", json={"action": "save"}).status_code == 404
        a.cookies.clear()
        assert a.get("/api/matches").status_code == 401
        assert len(ids) == 4
