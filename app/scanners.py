# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Job sources: public, login-free JSON APIs only (no LinkedIn/Indeed or other login-walled sites).

Feeds: Remotive, RemoteOK, Arbeitnow, Hacker News "Who is hiring?" (Algolia API).
Company boards (from data/companies.json + extra slugs): Greenhouse, Lever, Ashby,
Workable, SmartRecruiters, Recruitee.

All HTTP goes through one shared app.polite.PoliteClient (per-host rate limits,
ETag/If-Modified-Since caching, retries with backoff). Fetchers raise on failure;
the scheduler isolates failures per source.
"""
from __future__ import annotations

import html
import re
from typing import Awaitable, Callable, Iterable, Optional

from app.config import get_settings
from app.polite import PoliteClient
from app.registry import ATS, Company, company_index, registry
from app.scanner.base import REMOTE_PATTERNS
from app.scheduler import ScannedJob

_TAGS = re.compile(r"<[^>]+>")
FEEDS = ("remotive", "remoteok", "arbeitnow", "hn")
SOURCES = set(FEEDS) | set(ATS)

_shared: Optional[PoliteClient] = None


def get_client() -> PoliteClient:
    """One long-lived client so per-host limits and the ETag cache span cycles."""
    global _shared
    if _shared is None:
        s = get_settings()
        _shared = PoliteClient(user_agent=s.scanner_user_agent, timeout=s.scan_timeout_seconds,
                               per_host_concurrency=s.per_host_concurrency,
                               min_interval=s.per_host_min_interval_seconds, retries=s.http_retries)
    return _shared


def set_client(client: Optional[PoliteClient]) -> None:
    global _shared
    _shared = client


def _text(value) -> str:
    # Some APIs (e.g. Greenhouse) return entity-escaped HTML, so unescape before stripping tags.
    raw = html.unescape(str(value or ""))
    raw = re.sub(r"(?i)<\s*(br|/p|/li|p)\b[^>]*>", "\n", raw)
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(_TAGS.sub(" ", raw))).replace(" \n", "\n").strip()


def _flat(value) -> str:
    return re.sub(r"\s+", " ", _text(value)).strip()


def _is_remote(*parts) -> bool:
    return bool(REMOTE_PATTERNS.search(" ".join(str(p or "") for p in parts)))


async def _get(url: str):
    return await get_client().get_json(url)


# ---------------------------------------------------------------- feeds

async def fetch_remotive() -> list[ScannedJob]:
    data = await _get("https://remotive.com/api/remote-jobs")
    return [ScannedJob(source="remotive", external_id=str(j["id"]), title=_flat(j.get("title")),
                       company=_flat(j.get("company_name")),
                       location=_flat(j.get("candidate_required_location")) or "Remote",
                       url=j.get("url", ""), description=_flat(j.get("description")), remote=True,
                       sector=_flat(j.get("category")))
            for j in data.get("jobs", []) if j.get("id") and j.get("title")]


async def fetch_remoteok() -> list[ScannedJob]:
    # RemoteOK terms: link back to RemoteOK and credit it as the source. We keep the
    # remoteok.com URL as the job link and record source="remoteok".
    data = await _get("https://remoteok.com/api")
    out = []
    for j in data:
        if not isinstance(j, dict) or "id" not in j or not j.get("position"):
            continue  # first element is the legal/attribution notice
        out.append(ScannedJob(source="remoteok", external_id=str(j["id"]), title=_flat(j.get("position")),
                              company=_flat(j.get("company")), location=_flat(j.get("location")) or "Remote",
                              url=j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug', j['id'])}",
                              description=_flat(j.get("description")) + _salary_text(
                                  j.get("salary_min"), j.get("salary_max"), "USD"), remote=True))
    return out


async def fetch_arbeitnow() -> list[ScannedJob]:
    data = await _get("https://www.arbeitnow.com/api/job-board-api")
    return [ScannedJob(source="arbeitnow", external_id=str(j["slug"]), title=_flat(j.get("title")),
                       company=_flat(j.get("company_name")), location=_flat(j.get("location")),
                       url=j.get("url", ""), description=_flat(j.get("description")),
                       remote=bool(j.get("remote")) or _is_remote(j.get("location", "")))
            for j in data.get("data", []) if j.get("slug") and j.get("title")]


HN_SEARCH = ("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring"
             "&query=%22who%20is%20hiring%22&hitsPerPage=5")
_ROLE_WORDS = re.compile(r"(?i)\b(engineer|developer|scientist|designer|manager|lead|head|director|analyst|"
                         r"researcher|writer|specialist|founding|architect|product|marketing|sales|ops|"
                         r"operations|recruiter|teacher|tutor|nurse|counsel|intern|staff)\b")
_LOCATION_WORDS = re.compile(r"(?i)\b(remote|onsite|on-site|hybrid|usa?|uk|eu|europe|global|worldwide|"
                             r"[A-Z][a-z]+,\s*[A-Z]{2})\b")


def parse_hn_post(comment: dict) -> Optional[ScannedJob]:
    """Turn one top-level 'Who is hiring?' comment into a job (best effort, HN's informal format)."""
    raw = comment.get("text") or ""
    if not raw or comment.get("author") in (None, "") or "|" not in raw.split("<p>")[0]:
        return None
    text = _text(raw)
    header = text.split("\n", 1)[0]
    parts = [p.strip() for p in header.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company = parts[0][:200]
    title = next((p for p in parts[1:] if _ROLE_WORDS.search(p)), parts[1])[:300]
    location = next((p for p in parts[1:] if p is not title and _LOCATION_WORDS.search(p)), "")[:200]
    cid = str(comment.get("id"))
    return ScannedJob(source="hn", external_id=cid, title=title, company=company, location=location,
                      url=f"https://news.ycombinator.com/item?id={cid}", description=re.sub(r"\s+", " ", text),
                      remote=_is_remote(header))


async def fetch_hn() -> list[ScannedJob]:
    hits = (await _get(HN_SEARCH)).get("hits", [])
    thread = next((h for h in hits if str(h.get("title", "")).lower().startswith("ask hn: who is hiring")), None)
    if thread is None:
        return []
    item = await _get(f"https://hn.algolia.com/api/v1/items/{thread['objectID']}")
    out = []
    for c in item.get("children") or []:
        job = parse_hn_post(c)
        if job:
            out.append(job)
    return out


# ---------------------------------------------------------------- company boards

def _salary_text(lo, hi, currency="", period="") -> str:
    try:
        lo_i, hi_i = int(float(lo or 0)), int(float(hi or 0))
    except (TypeError, ValueError):
        return ""
    if not lo_i and not hi_i:
        return ""
    rng = f"{lo_i:,}–{hi_i:,}" if lo_i and hi_i else f"{lo_i or hi_i:,}"
    return f"\nSalary: {rng} {currency or ''} {period or ''}".rstrip()


def _co(c: Company) -> dict:
    return {"company": c.name or c.slug, "sector": c.sector}


async def fetch_greenhouse(c: Company) -> list[ScannedJob]:
    data = await _get(f"https://boards-api.greenhouse.io/v1/boards/{c.slug}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        loc = _flat((j.get("location") or {}).get("name"))
        out.append(ScannedJob(source=f"greenhouse:{c.slug}", external_id=str(j["id"]), title=_flat(j.get("title")),
                              location=loc, url=j.get("absolute_url", ""), description=_flat(j.get("content")),
                              remote=_is_remote(loc, j.get("title", "")), **_co(c)))
    return out


async def fetch_lever(c: Company) -> list[ScannedJob]:
    data = await _get(f"https://api.lever.co/v0/postings/{c.slug}?mode=json")
    out = []
    for j in data:
        loc = _flat((j.get("categories") or {}).get("location"))
        rng = j.get("salaryRange") or {}
        out.append(ScannedJob(source=f"lever:{c.slug}", external_id=str(j["id"]), title=_flat(j.get("text")),
                              location=loc, url=j.get("hostedUrl", ""),
                              description=_flat(j.get("descriptionPlain") or j.get("description"))
                              + _salary_text(rng.get("min"), rng.get("max"), rng.get("currency"), rng.get("interval")),
                              remote=(j.get("workplaceType") == "remote") or _is_remote(loc), **_co(c)))
    return out


async def fetch_ashby(c: Company) -> list[ScannedJob]:
    data = await _get(f"https://api.ashbyhq.com/posting-api/job-board/{c.slug}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = _flat(j.get("location"))
        comp = _flat((j.get("compensation") or {}).get("scrapeableCompensationSalarySummary"))
        out.append(ScannedJob(source=f"ashby:{c.slug}", external_id=str(j["id"]), title=_flat(j.get("title")),
                              location=loc, url=j.get("jobUrl", ""),
                              description=_flat(j.get("descriptionPlain")) + (f"\nSalary: {comp}" if comp else ""),
                              remote=bool(j.get("isRemote")) or _is_remote(loc), **_co(c)))
    return out


async def fetch_workable(c: Company) -> list[ScannedJob]:
    data = await _get(f"https://apply.workable.com/api/v1/widget/accounts/{c.slug}?details=true")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        remote = str(j.get("telecommuting")).lower() == "true" or _is_remote(loc)
        out.append(ScannedJob(source=f"workable:{c.slug}", external_id=str(j.get("shortcode") or j.get("url")),
                              title=_flat(j.get("title")), location=loc, url=j.get("url") or j.get("shortlink", ""),
                              description=_flat(j.get("description")), remote=remote,
                              company=c.name or _flat(data.get("name")) or c.slug, sector=c.sector))
    return out


async def fetch_smartrecruiters(c: Company) -> list[ScannedJob]:
    data = await _get(f"https://api.smartrecruiters.com/v1/companies/{c.slug}/postings?limit=100")
    out = []
    for j in data.get("content", []):
        loc_d = j.get("location") or {}
        loc = ", ".join(x for x in (loc_d.get("city"), loc_d.get("region"), loc_d.get("country")) if x)
        labels = [((j.get(k) or {}).get("label") or "") for k in ("function", "industry", "experienceLevel")]
        out.append(ScannedJob(source=f"smartrecruiters:{c.slug}", external_id=str(j["id"]), title=_flat(j.get("name")),
                              location=loc, url=f"https://jobs.smartrecruiters.com/{c.slug}/{j['id']}",
                              description=" ".join(x for x in labels if x),
                              remote=bool(loc_d.get("remote")) or _is_remote(loc),
                              company=c.name or (j.get("company") or {}).get("name") or c.slug,
                              sector=c.sector or labels[1]))
    return out


async def fetch_recruitee(c: Company) -> list[ScannedJob]:
    data = await _get(f"https://{c.slug}.recruitee.com/api/offers/")
    out = []
    for j in data.get("offers", []):
        sal = j.get("salary") or {}
        out.append(ScannedJob(source=f"recruitee:{c.slug}", external_id=str(j["id"]), title=_flat(j.get("title")),
                              location=_flat(j.get("location")), url=j.get("careers_url", ""),
                              description=_flat(j.get("description")) + " " + _flat(j.get("requirements"))
                              + _salary_text(sal.get("min"), sal.get("max"), sal.get("currency"), sal.get("period")),
                              remote=bool(j.get("remote")) or _is_remote(j.get("location")),
                              company=c.name or _flat(j.get("company_name")) or c.slug, sector=c.sector))
    return out


BOARD_FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
                  "workable": fetch_workable, "smartrecruiters": fetch_smartrecruiters,
                  "recruitee": fetch_recruitee}
FEED_FETCHERS = {"remotive": fetch_remotive, "remoteok": fetch_remoteok, "arbeitnow": fetch_arbeitnow,
                 "hn": fetch_hn}
_EXTRA_SETTING = {"greenhouse": "greenhouse_boards", "lever": "lever_companies", "ashby": "ashby_boards",
                  "workable": "workable_accounts", "smartrecruiters": "smartrecruiters_companies",
                  "recruitee": "recruitee_companies"}

Fetcher = Callable[[], Awaitable[Iterable[ScannedJob]]]


def _per_board(c: Company) -> Fetcher:
    fn = BOARD_FETCHERS[c.ats]

    async def fetch():
        return await fn(c)
    fetch.__name__ = f"{c.ats}[{c.slug}]"
    return fetch


def enabled_sources() -> set[str]:
    s = get_settings()
    return {x.lower() for x in s.csv_list(s.scanners_enabled)} & SOURCES


def all_boards() -> list[Company]:
    """Every enabled company board: registry entries plus extra slugs from settings."""
    s = get_settings()
    enabled = enabled_sources()
    idx = company_index()
    out: list[Company] = []
    seen: set[tuple[str, str]] = set()
    if s.use_company_registry:
        for c in registry():
            if c.ats in enabled and (c.ats, c.slug.lower()) not in seen:
                seen.add((c.ats, c.slug.lower()))
                out.append(c)
    for ats, attr in _EXTRA_SETTING.items():
        if ats not in enabled:
            continue
        for slug in s.csv_list(getattr(s, attr)):
            if (ats, slug.lower()) not in seen:
                seen.add((ats, slug.lower()))
                out.append(idx.get((ats, slug.lower())) or Company(ats, slug, slug))
    return out


def rotate(boards: list, cursor: int, n: int) -> tuple[list, int]:
    """Take n boards starting at cursor (wrapping); return them and the next cursor."""
    if not boards or n <= 0:
        return [], 0
    cursor %= len(boards)
    if n >= len(boards):
        return list(boards), 0
    chunk = (boards + boards)[cursor:cursor + n]
    return chunk, (cursor + n) % len(boards)


def build_scanners(cursor: int = 0) -> tuple[list[Fetcher], int]:
    """Feeds every cycle + the next slice of company boards. Returns (scanners, next_cursor)."""
    enabled = enabled_sources()
    out: list[Fetcher] = [fn for name, fn in FEED_FETCHERS.items() if name in enabled]
    boards, nxt = rotate(all_boards(), cursor, get_settings().boards_per_cycle)
    out.extend(_per_board(c) for c in boards)
    return out, nxt
