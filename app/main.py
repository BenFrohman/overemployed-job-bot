# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""FastAPI application: auth, tenant-scoped jobs/applications, billing."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import billing
from app.auth import (
    Permission, assert_own_resource, hash_password, require_admin,
    require_authenticated, require_permission, scope_user_id, verify_password,
)
from app.auth.deps import AuthUserMiddleware
from app.auth.tokens import create_session_token
from app.config import get_settings
from app.database import get_db, init_db
from app.models import Application, AuditLog, JobListing, User
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
    user = require_authenticated(request)
    if not user.has_access():
        raise HTTPException(402, "Trial expired — unlock lifetime access")
    return user


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
    return {"id": u.id, "email": u.email, "is_admin": u.is_admin, "lifetime_paid": u.lifetime_paid,
            "trial_ends_at": u.trial_ends_at.isoformat() if u.trial_ends_at else None,
            "has_access": u.has_access()}


@app.get("/", response_class=HTMLResponse)
async def landing():
    return (f"<!doctype html><title>{settings.app_name}</title><h1>{settings.app_name}</h1>"
            f"<p>{settings.trial_hours}-hour free trial, then ${settings.stripe_price_lifetime_cents / 100:.0f} "
            "one-time lifetime access.</p><p><a href='/app'>Open the app</a></p>")


@app.get("/app", response_class=HTMLResponse)
async def app_shell(request: Request):
    user = getattr(request.state, "user", None)
    who = user.email if user else "not signed in"
    return f"<!doctype html><title>{settings.app_name}</title><h1>App</h1><p>{who}</p>"


@app.get("/health")
async def health():
    return {"ok": True, "app": settings.app_name, "stripe": billing.stripe_configured()}


@app.post("/api/signup")
async def signup(body: Credentials, request: Request, db: AsyncSession = Depends(get_db)):
    if not rate_limiter.allow(f"signup:{client_ip(request)}", settings.login_rate_limit, settings.login_rate_window_seconds):
        raise HTTPException(429, "Too many attempts")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    user.start_trial(settings.trial_hours)
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
async def jobs(request: Request, limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    require_access(request)
    limit = max(1, min(limit, 200))
    rows = (await db.execute(select(JobListing).order_by(JobListing.discovered_at.desc())
                             .limit(limit).offset(max(0, offset)))).scalars().all()
    return [{"id": j.id, "source": j.source, "title": j.title, "company": j.company,
             "location": j.location, "url": j.url} for j in rows]


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


@app.post("/api/billing/checkout")
async def checkout(request: Request):
    user = require_authenticated(request)
    if user.lifetime_paid:
        return {"already_paid": True}
    if not billing.stripe_configured():
        raise HTTPException(503, "Billing is not configured")
    return {"url": billing.create_checkout_session(user.id, user.email)}


@app.post("/api/billing/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    try:
        event = billing.parse_webhook(payload, request.headers.get("stripe-signature", ""))
    except ValueError:
        raise HTTPException(400, "Invalid webhook")
    uid = billing.paid_user_id(event)
    if uid is not None:
        user = await db.get(User, uid)
        if user is not None and not user.lifetime_paid:
            user.lifetime_paid = True
            user.stripe_customer_id = event["data"]["object"].get("customer")
            await audit(db, request, "lifetime_unlocked", uid, event.get("id", ""))
            await db.commit()
    return {"received": True}


@app.post("/api/dev/unlock")
async def dev_unlock(request: Request, db: AsyncSession = Depends(get_db)):
    """Local development only: unlock without Stripe when Stripe is unconfigured and the client is loopback."""
    user = require_authenticated(request)
    host = request.client.host if request.client else ""
    if billing.stripe_configured() or host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(404, "Not found")
    u = await db.get(User, user.id)
    u.lifetime_paid = True
    await audit(db, request, "dev_unlock", u.id)
    await db.commit()
    return _user_out(u)


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
