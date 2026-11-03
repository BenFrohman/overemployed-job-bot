# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""FastAPI application: auth and tenant-scoped jobs/applications/preferences."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    Permission, assert_own_resource, hash_password, require_admin,
    require_authenticated, require_permission, scope_user_id, verify_password,
)
from app.auth.deps import AuthUserMiddleware
from app.auth.tokens import create_session_token
from app.config import get_settings
from app.database import get_db, init_db
from app.models import Application, AuditLog, JobListing, User, UserPreference
from app.preferences import router as preferences_router
from app.security import client_ip, rate_limiter

settings = get_settings()

APP_STATUSES = {"saved", "applied", "interviewing", "offer", "rejected", "withdrawn"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(AuthUserMiddleware)
app.include_router(preferences_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


async def audit(db: AsyncSession, request: Request, action: str, user_id: Optional[int] = None, detail: str = ""):
    db.add(AuditLog(user_id=user_id, action=action, detail=detail[:2000], ip=client_ip(request)))


def require_access(request: Request) -> User:
    """Every signed-in user has full access; data stays scoped to the user."""
    return require_authenticated(request)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class ApplicationIn(BaseModel):
    job_id: int
    status: str = "saved"
    notes: str = Field(default="", max_length=5000)


class ApplicationPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=5000)


def _set_session(resp: Response, user_id: int) -> None:
    resp.set_cookie(settings.session_cookie_name, create_session_token(user_id), httponly=True,
                    secure=settings.secure_cookies, samesite="lax", max_age=settings.session_hours * 3600)


def _user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "is_admin": u.is_admin}


@app.get("/", response_class=HTMLResponse)
async def landing():
    return (f"<!doctype html><title>{settings.app_name}</title><h1>{settings.app_name}</h1>"
            "<p>Free and open source remote job finder.</p><p><a href='/app'>Open the app</a></p>")


@app.get("/app", response_class=HTMLResponse)
async def app_shell(request: Request):
    user = getattr(request.state, "user", None)
    who = user.email if user else "not signed in"
    return f"<!doctype html><title>{settings.app_name}</title><h1>App</h1><p>{who}</p>"


@app.get("/health")
async def health():
    return {"ok": True, "app": settings.app_name}


@app.post("/api/signup")
async def signup(body: Credentials, request: Request, db: AsyncSession = Depends(get_db)):
    if not rate_limiter.allow(f"signup:{client_ip(request)}", settings.login_rate_limit, settings.login_rate_window_seconds):
        raise HTTPException(429, "Too many attempts")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Email already registered")
    await audit(db, request, "signup", user.id)
    await db.commit()
    resp = JSONResponse(_user_out(user), status_code=201)
    _set_session(resp, user.id)
    return resp


@app.post("/api/login")
async def login(body: Credentials, request: Request, db: AsyncSession = Depends(get_db)):
    key = f"login:{client_ip(request)}"
    if not rate_limiter.allow(key, settings.login_rate_limit, settings.login_rate_window_seconds):
        raise HTTPException(429, "Too many attempts")
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        await audit(db, request, "login_failed", None, body.email.lower())
        await db.commit()
        raise HTTPException(401, "Invalid email or password")
    await audit(db, request, "login", user.id)
    await db.commit()
    resp = JSONResponse(_user_out(user))
    _set_session(resp, user.id)
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(settings.session_cookie_name)
    return resp


@app.get("/api/me")
async def me(request: Request):
    return _user_out(require_authenticated(request))


@app.get("/api/jobs")
async def jobs(request: Request, limit: int = 50, offset: int = 0, all: bool = False,
               db: AsyncSession = Depends(get_db)):
    """Shared catalog, filtered by the caller's own preferences unless all=true."""
    user = require_access(request)
    limit = max(1, min(limit, 200))
    q = select(JobListing).order_by(JobListing.discovered_at.desc(), JobListing.id.desc())
    pref = None if all else (await db.execute(
        select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    if pref is not None:
        if pref.remote_only:
            q = q.where(JobListing.remote.is_(True))
        kws = pref.keyword_list()
        if kws:
            q = q.where(or_(*[or_(func.lower(JobListing.title).contains(k),
                                  func.lower(JobListing.description).contains(k)) for k in kws]))
    rows = (await db.execute(q.limit(limit).offset(max(0, offset)))).scalars().all()
    return [{"id": j.id, "source": j.source, "title": j.title, "company": j.company,
             "location": j.location, "remote": j.remote, "url": j.url} for j in rows]


def _app_out(a: Application) -> dict:
    return {"id": a.id, "user_id": a.user_id, "job_id": a.job_id, "status": a.status, "notes": a.notes}


@app.get("/api/applications")
async def list_applications(request: Request, user_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    user = require_access(request)
    uid = scope_user_id(user, user_id)
    rows = (await db.execute(select(Application).where(Application.user_id == uid))).scalars().all()
    return [_app_out(a) for a in rows]


@app.post("/api/applications", status_code=201)
async def create_application(body: ApplicationIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_access(request)
    if body.status not in APP_STATUSES:
        raise HTTPException(422, "invalid status")
    if await db.get(JobListing, body.job_id) is None:
        raise HTTPException(404, "Job not found")
    a = Application(user_id=user.id, job_id=body.job_id, status=body.status, notes=body.notes)
    db.add(a)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Already tracking this job")
    return _app_out(a)


@app.patch("/api/applications/{app_id}")
async def update_application(app_id: int, body: ApplicationPatch, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_access(request)
    a = await db.get(Application, app_id)
    assert_own_resource(user, a.user_id if a else None)
    if body.status is not None:
        if body.status not in APP_STATUSES:
            raise HTTPException(422, "invalid status")
        a.status = body.status
    if body.notes is not None:
        a.notes = body.notes
    await db.commit()
    return _app_out(a)


@app.delete("/api/applications/{app_id}")
async def delete_application(app_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_access(request)
    a = await db.get(Application, app_id)
    assert_own_resource(user, a.user_id if a else None)
    await db.delete(a)
    await db.commit()
    return {"ok": True}



@app.get("/api/admin/users")
async def admin_users(request: Request, db: AsyncSession = Depends(get_db),
                      _=Depends(require_permission(Permission.VIEW_ALL_USERS))):
    rows = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return [_user_out(u) for u in rows]


@app.get("/api/admin/audit")
async def admin_audit(request: Request, limit: int = 100, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500))))).scalars().all()
    return [{"id": r.id, "user_id": r.user_id, "action": r.action, "detail": r.detail, "ip": r.ip,
             "at": r.created_at.isoformat()} for r in rows]
