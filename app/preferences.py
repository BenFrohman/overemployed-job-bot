# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Per-user job preferences: each user chooses their own field and keywords."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_authenticated
from app.database import get_db
from app.models import UserPreference

router = APIRouter()


class PreferencesIn(BaseModel):
    field: str = Field(default="", max_length=128)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    remote_only: bool = True


def _out(p: UserPreference | None) -> dict:
    if p is None:
        return {"field": "", "keywords": [], "remote_only": True}
    return {"field": p.field, "keywords": p.keyword_list(), "remote_only": p.remote_only}


@router.get("/api/preferences")
async def get_preferences(request: Request, db: AsyncSession = Depends(get_db)):
    user = require_authenticated(request)
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    return _out(pref)


@router.post("/api/preferences")
async def set_preferences(body: PreferencesIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = require_authenticated(request)
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.field = body.field.strip()
    pref.keywords = ",".join(k.strip().replace(",", " ")[:64] for k in body.keywords if k.strip())
    pref.remote_only = body.remote_only
    await db.commit()
    return _out(pref)
