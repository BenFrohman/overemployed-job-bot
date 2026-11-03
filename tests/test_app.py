# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.


import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, verify_password, scope_user_id  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import JobListing  # noqa: E402


def _add_job():
    async def go():
        async with AsyncSessionLocal() as db:
            j = JobListing(source="t", external_id="1", title="AI tutor (remote)", remote=True)  # source "t" = test-only
            db.add(j)
            await db.commit()
            return j.id
    return asyncio.run(go())


def test_passwords():
    h = hash_password("hunter22!")
    assert verify_password("hunter22!", h) and not verify_password("nope", h)


def test_flow_and_tenant_isolation():
    with TestClient(app) as a, TestClient(app) as b:
        assert a.post("/api/signup", json={"email": "A@x.io", "password": "password1"}).status_code == 201
        assert a.post("/api/signup", json={"email": "a@x.io", "password": "password1"}).status_code == 409
        assert b.post("/api/signup", json={"email": "b@x.io", "password": "password2"}).status_code == 201
        assert a.get("/api/me").json()["is_admin"] is False
        jid = _add_job()
        assert len(a.get("/api/jobs").json()) == 1
        app_id = a.post("/api/applications", json={"job_id": jid}).json()["id"]
        assert b.patch(f"/api/applications/{app_id}", json={"status": "applied"}).status_code == 404
        assert b.get("/api/applications", params={"user_id": 1}).status_code == 403
        assert a.patch(f"/api/applications/{app_id}", json={"status": "applied"}).json()["status"] == "applied"
        assert a.post("/api/preferences", json={"field": "math", "keywords": ["tutor"]}).json()["keywords"] == ["tutor"]
        assert b.get("/api/preferences").json()["field"] == ""
        assert b.get("/api/admin/users").status_code == 403
        assert a.post("/api/billing/checkout").status_code == 404  # no paid plan exists
        assert len(a.get("/api/jobs").json()) == 1  # matches a's keyword "tutor"
        a.post("/api/preferences", json={"keywords": ["astronomy"]})
        assert a.get("/api/jobs").json() == []
        assert len(a.get("/api/jobs", params={"all": True}).json()) == 1
        a.post("/api/logout")
        a.cookies.clear()
        assert a.get("/api/me").status_code == 401
        assert a.post("/api/login", json={"email": "a@x.io", "password": "wrongpass"}).status_code == 401
        assert a.post("/api/login", json={"email": "a@x.io", "password": "password1"}).status_code == 200
