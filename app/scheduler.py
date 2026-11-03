# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Periodic job scanning into the shared JobListing catalog."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable, Iterable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Application, JobFeedback, JobListing, ScanState, utcnow
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
    sector: str = ""


Scanner = Callable[[], Awaitable[Iterable[ScannedJob]]]
SCANNERS: list[Scanner] = []
_scheduler: AsyncIOScheduler | None = None


def register_scanner(fn: Scanner) -> Scanner:
    SCANNERS.append(fn)
    return fn


def _keep(j: ScannedJob) -> bool:
    if not j.title or not j.external_id:
        return False
    if get_settings().catalog_filter == "applicable":
        return looks_applicable(j.title, j.description, j.location)
    return True


async def store_jobs(jobs: Iterable[ScannedJob]) -> int:
    """Insert new jobs (deduped by source+external_id), refresh last_seen on known ones."""
    added = 0
    seen: set[tuple[str, str]] = set()
    now = utcnow()
    async with AsyncSessionLocal() as db:
        for j in jobs:
            key = (j.source, j.external_id)
            if key in seen or not _keep(j):
                continue
            seen.add(key)
            existing = (await db.execute(select(JobListing).where(
                JobListing.source == j.source, JobListing.external_id == j.external_id))).scalar_one_or_none()
            if existing is not None:
                existing.last_seen_at = now
                continue
            db.add(JobListing(source=j.source[:64], external_id=j.external_id[:256], title=j.title[:512],
                              company=j.company[:256], location=j.location[:256], url=j.url[:1024],
                              description=j.description[:20000], remote=j.remote, sector=j.sector[:128],
                              last_seen_at=now))
            added += 1
        await db.commit()
    return added


async def prune_stale_jobs() -> int:
    """Delete listings not seen for job_retention_days unless a user saved/tracked them."""
    cutoff = utcnow() - timedelta(days=get_settings().job_retention_days)
    async with AsyncSessionLocal() as db:
        kept = select(Application.job_id).union(select(JobFeedback.job_id).where(JobFeedback.action == "save"))
        res = await db.execute(delete(JobListing).where(JobListing.last_seen_at < cutoff,
                                                        JobListing.id.not_in(kept)))
        await db.commit()
        return res.rowcount or 0


async def _get_state(key: str, default: str = "") -> str:
    async with AsyncSessionLocal() as db:
        row = await db.get(ScanState, key)
        return row.value if row else default


async def _set_state(key: str, value: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(ScanState, key)
        if row is None:
            db.add(ScanState(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def _run_one(scanner: Scanner) -> tuple[str, int, Optional[str]]:
    name = getattr(scanner, "__name__", str(scanner))
    try:
        return name, await store_jobs(await scanner()), None
    except Exception as e:  # one broken source must not stop the others
        return name, 0, f"{type(e).__name__}: {e}"


async def run_scan_cycle() -> int:
    """Run feeds + the next rotation slice of company boards concurrently.

    Per-host politeness is enforced by the shared PoliteClient; failures are isolated.
    """
    from app.scanners import build_scanners
    manual = list(SCANNERS)
    cursor = int(await _get_state("board_cursor", "0") or 0)
    if manual:
        scanners, nxt = manual, cursor
    else:
        scanners, nxt = build_scanners(cursor)
    results = await asyncio.gather(*(_run_one(s) for s in scanners))
    if not manual:
        await _set_state("board_cursor", str(nxt))
    total = sum(n for _, n, _ in results)
    failed = [(name, err) for name, _, err in results if err]
    for name, err in failed[:20]:
        print(f"[scan] {name} failed: {err}")
    pruned = await prune_stale_jobs()
    print(f"[scan] cycle done: {total} new job(s) from {len(scanners)} scanner(s), "
          f"{len(failed)} failed, {pruned} stale pruned")
    return total


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(run_scan_cycle, "interval",
                           minutes=get_settings().scan_interval_minutes, id="scan", max_instances=1)
        _scheduler.start()
    return _scheduler
