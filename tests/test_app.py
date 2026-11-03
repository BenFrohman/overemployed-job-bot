# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
import os
import tempfile

_db = tempfile.mkdtemp()
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-0123456789")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db}/t.db"
os.environ["STRIPE_SECRET_KEY"] = ""

import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, verify_password, scope_user_id  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import JobListing  # noqa: E402


def _add_job():
    async def go():
        async with AsyncSessionLocal() as db:
            j = JobListing(source="t", external_id="1", title="AI tutor (remote)")
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
        assert a.get("/api/me").json()["has_access"] is True
        jid = _add_job()
        assert len(a.get("/api/jobs").json()) == 1
        app_id = a.post("/api/applications", json={"job_id": jid}).json()["id"]
        assert b.patch(f"/api/applications/{app_id}", json={"status": "applied"}).status_code == 404
        assert b.get("/api/applications", params={"user_id": 1}).status_code == 403
        assert a.patch(f"/api/applications/{app_id}", json={"status": "applied"}).json()["status"] == "applied"
        assert a.post("/api/preferences", json={"field": "math", "keywords": ["tutor"]}).json()["keywords"] == ["tutor"]
        assert b.get("/api/preferences").json()["field"] == ""
        assert b.get("/api/admin/users").status_code == 403
        assert a.post("/api/billing/checkout").status_code == 503
        assert a.post("/api/billing/webhook", content=b"{}").status_code == 400
        a.post("/api/logout")
        a.cookies.clear()
        assert a.get("/api/me").status_code == 401
        assert a.post("/api/login", json={"email": "a@x.io", "password": "wrongpass"}).status_code == 401
        assert a.post("/api/login", json={"email": "a@x.io", "password": "password1"}).status_code == 200
