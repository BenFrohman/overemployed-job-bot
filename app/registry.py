# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Company job-board registry (data/companies.json).

Each entry: {"ats", "slug", "name", optional "domain", "sector"}. The file is
built and re-validated by scripts/refresh_companies.py; every entry answered its
ATS's public API when it was last refreshed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee")
REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "companies.json"
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@dataclass(frozen=True)
class Company:
    ats: str
    slug: str
    name: str = ""
    domain: str = ""
    sector: str = ""


def valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug or ""))


def probe_url(ats: str, slug: str) -> str:
    """Cheapest public endpoint that proves a board exists."""
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
        "recruitee": f"https://{slug}.recruitee.com/api/offers/",
    }[ats]


def is_alive(ats: str, data: Any) -> bool:
    """Does a probe response show a real board? (404s are handled by the caller.)"""
    if ats == "greenhouse":
        return isinstance(data, dict) and bool(data.get("name"))
    if ats == "lever":
        return isinstance(data, list)
    if ats == "ashby":
        return isinstance(data, dict) and isinstance(data.get("jobs"), list)
    if ats == "workable":
        return isinstance(data, dict) and isinstance(data.get("jobs"), list)
    if ats == "smartrecruiters":
        # This API answers 200 with zero results even for unknown companies, so only a
        # board with at least one posting counts as proven.
        return isinstance(data, dict) and (data.get("totalFound") or 0) > 0
    if ats == "recruitee":
        return isinstance(data, dict) and isinstance(data.get("offers"), list)
    return False


def probe_name(ats: str, data: Any) -> str:
    if ats in ("greenhouse", "workable") and isinstance(data, dict):
        return str(data.get("name") or "")
    if ats == "smartrecruiters" and isinstance(data, dict) and data.get("content"):
        return str((data["content"][0].get("company") or {}).get("name") or "")
    return ""


def load_registry(path: Optional[Path] = None) -> list[Company]:
    p = Path(path or REGISTRY_PATH)
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    out = []
    for e in raw.get("companies", []):
        if e.get("ats") in ATS and valid_slug(e.get("slug", "")):
            out.append(Company(e["ats"], e["slug"], e.get("name", ""), e.get("domain", ""), e.get("sector", "")))
    return out


@lru_cache
def registry() -> tuple[Company, ...]:
    return tuple(load_registry())


@lru_cache
def company_index() -> dict[tuple[str, str], Company]:
    return {(c.ats, c.slug.lower()): c for c in registry()}
