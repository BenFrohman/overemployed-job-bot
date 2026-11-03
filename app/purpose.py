# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Profile, ranked matches and feedback endpoints. Everything is scoped to the caller."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_authenticated
from app.config import get_settings
from app.database import get_db
from app.matching import JobDoc, Profile, get_embedder, rank
from app.models import Application, JobFeedback, JobListing, UserProfile
from app.security import rate_limiter

router = APIRouter()
CANDIDATE_POOL = 5000  # most recent listings considered per ranking

_FIELDS = ("skills", "experience", "values", "causes", "desired_impact", "location")


class ProfileIn(BaseModel):
    skills: str = Field(default="", max_length=4000)
    experience: str = Field(default="", max_length=8000)
    values: str = Field(default="", max_length=4000)
    causes: str = Field(default="", max_length=2000)
    desired_impact: str = Field(default="", max_length=4000)
    location: str = Field(default="", max_length=256)
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] = "any"
    comp_floor: int = Field(default=0, ge=0, le=10_000_000)


class FeedbackIn(BaseModel):
    action: Literal["save", "dismiss", "clear"]


def _profile_out(p: UserProfile | None) -> dict:
    if p is None:
        return ProfileIn().model_dump()
    return {**{f: getattr(p, f) for f in _FIELDS}, "remote_preference": p.remote_preference,
            "comp_floor": p.comp_floor}


async def _get_profile(db: AsyncSession, user_id: int) -> UserProfile | None:
    return (await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))).scalar_one_or_none()


@router.get("/api/profile")
async def get_profile(request: Request, db: AsyncSession = Depends(get_db)):
    user = require_authenticated(request)
    return _profile_out(await _get_profile(db, user.id))


@router.put("/api/profile")
async def put_profile(body: ProfileIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_authenticated(request)
    p = await _get_profile(db, user.id)
    if p is None:
        p = UserProfile(user_id=user.id)
        db.add(p)
    for k, v in body.model_dump().items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    await db.commit()
    return _profile_out(p)


def _doc(j: JobListing) -> JobDoc:
    return JobDoc(id=j.id, title=j.title, company=j.company, location=j.location, description=j.description,
                  remote=j.remote, sector=j.sector or "", url=j.url, source=j.source)


@router.get("/api/matches")
async def matches(request: Request, limit: int = 20, db: AsyncSession = Depends(get_db)):
    user = require_authenticated(request)
    s = get_settings()
    if not rate_limiter.allow(f"match:{user.id}", s.match_rate_limit, 60):
        raise HTTPException(429, "Too many requests")
    p = await _get_profile(db, user.id)
    prof = Profile(**_profile_out(p))
    fb = (await db.execute(select(JobFeedback).where(JobFeedback.user_id == user.id))).scalars().all()
    saved_ids = {f.job_id for f in fb if f.action == "save"}
    dismissed_ids = {f.job_id for f in fb if f.action == "dismiss"}
    q = select(JobListing).order_by(JobListing.discovered_at.desc(), JobListing.id.desc()).limit(CANDIDATE_POOL)
    if prof.remote_preference == "remote":
        q = q.where(JobListing.remote.is_(True))
    pool = [_doc(j) for j in (await db.execute(q)).scalars().all()]
    fb_ids = saved_ids | dismissed_ids
    fb_jobs = {j.id: _doc(j) for j in (await db.execute(
        select(JobListing).where(JobListing.id.in_(fb_ids)))).scalars().all()} if fb_ids else {}
    embedder = get_embedder(s.embedding_model) if s.match_embeddings else None
    ranked = rank(prof, [j for j in pool if j.id not in saved_ids],
                  saved=[fb_jobs[i] for i in saved_ids if i in fb_jobs],
                  dismissed=[fb_jobs[i] for i in dismissed_ids if i in fb_jobs],
                  dismissed_ids=dismissed_ids, limit=max(1, min(limit, 100)), embedder=embedder)
    return {"engine": "bm25+embeddings" if embedder else "bm25",
            "profile_complete": bool(prof.skills and (prof.causes or prof.values)),
            "matches": [{"job": {"id": m.job.id, "title": m.job.title, "company": m.job.company,
                                 "location": m.job.location, "remote": m.job.remote, "sector": m.job.sector,
                                 "url": m.job.url, "source": m.job.source},
                         "score": m.score, "breakdown": m.parts, "why": m.why, "reasons": m.reasons}
                        for m in ranked]}


@router.post("/api/matches/{job_id}/feedback")
async def feedback(job_id: int, body: FeedbackIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_authenticated(request)
    if await db.get(JobListing, job_id) is None:
        raise HTTPException(404, "Job not found")
    row = (await db.execute(select(JobFeedback).where(JobFeedback.user_id == user.id,
                                                      JobFeedback.job_id == job_id))).scalar_one_or_none()
    if body.action == "clear":
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(JobFeedback(user_id=user.id, job_id=job_id, action=body.action))
    else:
        row.action = body.action
    if body.action == "save":  # saving also starts tracking it as an application
        exists = (await db.execute(select(Application.id).where(Application.user_id == user.id,
                                                               Application.job_id == job_id))).scalar_one_or_none()
        if exists is None:
            db.add(Application(user_id=user.id, job_id=job_id, status="saved"))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Conflict, try again")
    return {"job_id": job_id, "action": body.action}
