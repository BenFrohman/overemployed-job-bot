# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Periodic job scanning into the shared JobListing catalog."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import JobListing
from app.scanner.base import looks_applicable


@dataclass
class ScannedJob:
    source: str
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    description: str = ""
    remote: bool = False


Scanner = Callable[[], Awaitable[Iterable[ScannedJob]]]
SCANNERS: list[Scanner] = []
_scheduler: AsyncIOScheduler | None = None


def register_scanner(fn: Scanner) -> Scanner:
    SCANNERS.append(fn)
    return fn


async def store_jobs(jobs: Iterable[ScannedJob]) -> int:
    """Insert applicable, not-yet-seen jobs. Returns the number added."""
    added = 0
    seen: set[tuple[str, str]] = set()
    async with AsyncSessionLocal() as db:
        for j in jobs:
            key = (j.source, j.external_id)
            if key in seen:
                continue
            seen.add(key)
            if not looks_applicable(j.title, j.description, j.location):
                continue
            exists = await db.execute(select(JobListing.id).where(
                JobListing.source == j.source, JobListing.external_id == j.external_id))
            if exists.scalar_one_or_none() is not None:
                continue
            db.add(JobListing(source=j.source, external_id=j.external_id, title=j.title,
                              company=j.company, location=j.location, url=j.url,
                              description=j.description, remote=j.remote))
            added += 1
        await db.commit()
    return added


def register_enabled_scanners() -> None:
    """Register the scanners selected by SCANNERS_ENABLED (idempotent)."""
    from app.scanners import build_scanners
    SCANNERS.clear()
    for fn in build_scanners():
        register_scanner(fn)


async def run_scan_cycle() -> int:
    if not SCANNERS:
        register_enabled_scanners()
    total = 0
    for scanner in SCANNERS:
        try:
            total += await store_jobs(await scanner())
        except Exception as e:  # one broken source must not stop the others
            print(f"[scan] {getattr(scanner, '__name__', scanner)} failed: {e}")
    print(f"[scan] cycle done: {total} new job(s) from {len(SCANNERS)} scanner(s)")
    return total


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(run_scan_cycle, "interval",
                           minutes=get_settings().scan_interval_minutes, id="scan", max_instances=1)
        _scheduler.start()
    return _scheduler
