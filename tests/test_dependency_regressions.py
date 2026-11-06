# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Exercise dependency-sensitive authentication, validation and async database paths."""
import asyncio
import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.tokens import create_session_token, decode_session_token
from app.config import Settings, get_settings
from app.database import _add_missing_columns
from app.main import app, ApplicationPatch


def _token(payload, *, wrong_key=False, algorithm="HS256"):
    settings = get_settings()
    key = "isolated-test-wrong-key-not-a-real-secret" if wrong_key else settings.secret_key
    return jwt.encode(payload, key, algorithm=algorithm)


def _claims(**overrides):
    now = int(datetime.now(timezone.utc).timestamp())
    return {"sub": "1", "iat": now, "exp": now + 3600, **overrides}


def test_session_token_round_trip():
    assert decode_session_token(create_session_token(42)) == 42


@pytest.mark.parametrize("kind", ["expired", "tampered", "wrong-key", "wrong-algorithm",
                                  "unsigned", "malformed", "missing-sub", "nonnumeric-sub", "null-sub"])
def test_invalid_tokens_fail_closed(kind):
    if kind == "expired":
        token = _token(_claims(exp=1))
    elif kind == "tampered":
        header, payload, signature = _token(_claims()).split(".")
        token = ".".join((header, payload, ("A" if signature[0] != "A" else "B") + signature[1:]))
    elif kind == "wrong-key":
        token = _token(_claims(), wrong_key=True)
    elif kind == "wrong-algorithm":
        token = _token(_claims(), algorithm="HS512")
    elif kind == "unsigned":
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
        token = encode({"alg": "none", "typ": "JWT"}) + "." + encode(_claims()) + "."
    elif kind == "malformed":
        token = "not.a.valid.jwt"
    else:
        payload = _claims()
        if kind == "missing-sub":
            del payload["sub"]
        else:
            payload["sub"] = None if kind == "null-sub" else "not-an-integer"
        token = _token(payload)
    assert decode_session_token(token) is None
    with TestClient(app) as client:
        client.cookies.set(get_settings().session_cookie_name, token)
        assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("body", [
    {"email": "not-an-email", "password": "password1"},
    {"email": "valid@example.com", "password": "short"},
    {"email": "valid@example.com", "password": 12345678},
    {"email": ["valid@example.com"], "password": "password1"},
])
def test_invalid_credentials_are_422(body):
    with TestClient(app) as client:
        assert client.post("/api/signup", json=body).status_code == 422
        assert client.post("/api/login", json=body).status_code == 422


def test_cookie_logout_lifespan_and_openapi():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert "/api/signup" in client.get("/openapi.json").json()["paths"]
        response = client.post("/api/signup", json={"email": "cookie@example.com", "password": "password1"})
        assert response.status_code == 201
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert client.get("/api/me").status_code == 200
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/me").status_code == 401


def test_settings_env_types_and_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / "settings.env"
    env_file.write_text("APP_PORT=8123\nSECURE_COOKIES=false\nSESSION_HOURS=12\n")
    monkeypatch.setenv("APP_PORT", "9123")
    monkeypatch.setenv("SECURE_COOKIES", "true")
    monkeypatch.delenv("SESSION_HOURS", raising=False)
    settings = Settings(_env_file=env_file)
    assert settings.app_port == 9123
    assert settings.secure_cookies is True
    assert settings.session_hours == 12
    patch = ApplicationPatch(notes="updated")
    assert patch.model_dump(exclude_unset=True) == {"notes": "updated"}
    assert ApplicationPatch().model_dump(exclude_unset=True) == {}


def test_populated_sqlite_forward_migration(tmp_path):
    async def check():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(320), password_hash VARCHAR(128))"))
                await connection.execute(text("INSERT INTO users (id, email, password_hash) VALUES (1, 'legacy@example.com', 'test-placeholder')"))
                await connection.run_sync(_add_missing_columns)
                columns = await connection.run_sync(lambda conn: {c["name"] for c in inspect(conn).get_columns("users")})
                assert {"is_admin", "created_at"} <= columns
                row = (await connection.execute(text("SELECT email, is_admin FROM users WHERE id=1"))).one()
                assert row == ("legacy@example.com", 0)
                await connection.run_sync(_add_missing_columns)  # idempotent, existing data retained
                assert (await connection.execute(text("SELECT count(*) FROM users"))).scalar_one() == 1
        finally:
            await engine.dispose()
    asyncio.run(check())
