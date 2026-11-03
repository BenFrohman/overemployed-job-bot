# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Job sources: public, login-free JSON APIs only.

Each fetcher returns normalized ScannedJob records. Network errors are raised to
the caller (run_scan_cycle), which isolates failures per source.
"""
from __future__ import annotations

import html
import re
from typing import Awaitable, Callable, Iterable

import httpx

from app.config import get_settings
from app.scanner.base import REMOTE_PATTERNS
from app.scheduler import ScannedJob

_TAGS = re.compile(r"<[^>]+>")


def _text(value) -> str:
    # Some APIs (e.g. Greenhouse) return entity-escaped HTML, so unescape before stripping tags.
    raw = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", raw))).strip()


def _is_remote(*parts: str) -> bool:
    return bool(REMOTE_PATTERNS.search(" ".join(p or "" for p in parts)))


def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(timeout=s.scan_timeout_seconds, follow_redirects=True,
                             headers={"User-Agent": s.scanner_user_agent, "Accept": "application/json"})


async def _get_json(url: str):
    async with _client() as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


async def fetch_remotive() -> list[ScannedJob]:
    data = await _get_json("https://remotive.com/api/remote-jobs")
    return [ScannedJob(source="remotive", external_id=str(j["id"]), title=_text(j.get("title")),
                       company=_text(j.get("company_name")),
                       location=_text(j.get("candidate_required_location")) or "Remote",
                       url=j.get("url", ""), description=_text(j.get("description")), remote=True)
            for j in data.get("jobs", []) if j.get("id") and j.get("title")]


async def fetch_remoteok() -> list[ScannedJob]:
    # RemoteOK terms: link back to RemoteOK and credit it as the source. We keep the
    # remoteok.com URL as the job link and record source="remoteok" (shown in the UI/API).
    data = await _get_json("https://remoteok.com/api")
    out = []
    for j in data:
        if not isinstance(j, dict) or "id" not in j or not j.get("position"):
            continue  # first element is the legal/attribution notice
        out.append(ScannedJob(source="remoteok", external_id=str(j["id"]), title=_text(j.get("position")),
                              company=_text(j.get("company")), location=_text(j.get("location")) or "Remote",
                              url=j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug', j['id'])}",
                              description=_text(j.get("description")), remote=True))
    return out


async def fetch_arbeitnow() -> list[ScannedJob]:
    data = await _get_json("https://www.arbeitnow.com/api/job-board-api")
    return [ScannedJob(source="arbeitnow", external_id=str(j["slug"]), title=_text(j.get("title")),
                       company=_text(j.get("company_name")), location=_text(j.get("location")),
                       url=j.get("url", ""), description=_text(j.get("description")),
                       remote=bool(j.get("remote")) or _is_remote(j.get("location", "")))
            for j in data.get("data", []) if j.get("slug") and j.get("title")]


async def fetch_greenhouse(board: str) -> list[ScannedJob]:
    data = await _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        loc = _text((j.get("location") or {}).get("name"))
        out.append(ScannedJob(source=f"greenhouse:{board}", external_id=str(j["id"]), title=_text(j.get("title")),
                              company=board, location=loc, url=j.get("absolute_url", ""),
                              description=_text(j.get("content")), remote=_is_remote(loc, j.get("title", ""))))
    return out


async def fetch_lever(company: str) -> list[ScannedJob]:
    data = await _get_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    out = []
    for j in data:
        loc = _text((j.get("categories") or {}).get("location"))
        remote = (j.get("workplaceType") == "remote") or _is_remote(loc)
        out.append(ScannedJob(source=f"lever:{company}", external_id=str(j["id"]), title=_text(j.get("text")),
                              company=company, location=loc, url=j.get("hostedUrl", ""),
                              description=_text(j.get("descriptionPlain") or j.get("description")), remote=remote))
    return out


async def fetch_ashby(board: str) -> list[ScannedJob]:
    data = await _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = _text(j.get("location"))
        out.append(ScannedJob(source=f"ashby:{board}", external_id=str(j["id"]), title=_text(j.get("title")),
                              company=board, location=loc, url=j.get("jobUrl", ""),
                              description=_text(j.get("descriptionPlain")),
                              remote=bool(j.get("isRemote")) or _is_remote(loc)))
    return out


Fetcher = Callable[[], Awaitable[Iterable[ScannedJob]]]


def _per_board(fn, slug: str) -> Fetcher:
    async def fetch():
        return await fn(slug)
    fetch.__name__ = f"{fn.__name__}[{slug}]"
    return fetch


def build_scanners() -> list[Fetcher]:
    """Scanners for the sources named in SCANNERS_ENABLED (board sources need slugs)."""
    s = get_settings()
    enabled = set(s.csv_list(s.scanners_enabled))
    out: list[Fetcher] = []
    for name, fn in (("remotive", fetch_remotive), ("remoteok", fetch_remoteok), ("arbeitnow", fetch_arbeitnow)):
        if name in enabled:
            out.append(fn)
    for name, fn, slugs in (("greenhouse", fetch_greenhouse, s.greenhouse_boards),
                            ("lever", fetch_lever, s.lever_companies),
                            ("ashby", fetch_ashby, s.ashby_boards)):
        if name in enabled:
            out.extend(_per_board(fn, slug) for slug in s.csv_list(slugs))
    return out


SOURCES = {"remotive", "remoteok", "arbeitnow", "greenhouse", "lever", "ashby"}
