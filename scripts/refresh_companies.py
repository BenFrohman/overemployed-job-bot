#!/usr/bin/env python3
# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Re-discover and validate the company job-board registry (data/companies.json).

Candidates come from openly licensed public datasets (see SEEDS; licenses and
attribution in NOTICE/README) plus the current registry. Every candidate is
probed against its ATS's public, login-free API; only boards that answer are
kept. Dead boards are dropped. Run weekly by .github/workflows/refresh-companies.yml.

    python scripts/refresh_companies.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.polite import FetchError, PoliteClient  # noqa: E402
from app.registry import ATS, REGISTRY_PATH, is_alive, probe_name, probe_url, valid_slug  # noqa: E402

UA = "overemployed-job-bot-registry/1.0 (+https://github.com/BenFrohman/overemployed-job-bot)"
LASTROUND = ("https://raw.githubusercontent.com/fyrosofttech/lastroundai-hiring-data/main/"
             "ats-directory/lastroundai-ats-company-directory-2026-08.csv")
AFRICA = "https://raw.githubusercontent.com/Thelastpoet/africa-ats-directory/main/companies/{ats}.json"

SEEDS = [
    {"id": "lastroundai", "name": "LastRound AI ATS Company Directory (2026-08)",
     "url": "https://github.com/fyrosofttech/lastroundai-hiring-data", "license": "CC-BY-4.0",
     "attribution": "LastRound AI, https://lastroundai.com/blog/salary-transparency-study-2026"},
    {"id": "africa-ats-directory", "name": "Africa ATS Directory",
     "url": "https://github.com/Thelastpoet/africa-ats-directory", "license": "MIT",
     "attribution": "Africa ATS Directory contributors"},
]


async def _text(client: PoliteClient, url: str) -> str:
    r = await client._client.get(url)
    r.raise_for_status()
    return r.text


async def gather_candidates(client: PoliteClient) -> dict[tuple[str, str], dict]:
    cands: dict[tuple[str, str], dict] = {}

    def add(ats, slug, name="", domain="", sector="", source="", known=False):
        slug = (slug or "").strip()
        if ats not in ATS or not valid_slug(slug) or slug.isdigit():
            return
        key = (ats, slug.lower())
        e = cands.setdefault(key, {"ats": ats, "slug": slug, "name": "", "sources": set()})
        e["name"] = e["name"] or name.strip()
        if domain and not e.get("domain"):
            e["domain"] = domain
        if sector and not e.get("sector"):
            e["sector"] = sector
        if source:
            e["sources"].add(source)
        e["known"] = e.get("known") or known

    if REGISTRY_PATH.exists():  # keep re-validating everything we already know
        for e in json.loads(REGISTRY_PATH.read_text()).get("companies", []):
            for src in e.get("sources") or [""]:
                add(e.get("ats"), e.get("slug"), e.get("name", ""), e.get("domain", ""), e.get("sector", ""),
                    src, known=True)
    try:
        for row in csv.DictReader(io.StringIO(await _text(client, LASTROUND))):
            add(row.get("ats_vendor", "").strip(), row.get("board_slug"), row.get("company_name", ""),
                source="lastroundai")
    except Exception as e:  # a seed going away must not wipe the registry
        print(f"[seed] lastroundai unavailable: {e}", file=sys.stderr)
    for ats in ATS:
        try:
            for e in json.loads(await _text(client, AFRICA.format(ats=ats))):
                meta = e.get("platform_metadata") or {}
                slug = meta.get("board_token") or meta.get("account_slug") or meta.get("org_slug") \
                    or meta.get("subdomain") or ""
                domain = (e.get("careers_url") or "").split("/")[2] if "//" in (e.get("careers_url") or "") else ""
                add(ats, slug, e.get("company", ""), domain, e.get("sector", ""), source="africa-ats-directory")
        except Exception as e:
            print(f"[seed] africa-ats-directory/{ats} unavailable: {e}", file=sys.stderr)
    return cands


async def validate(client: PoliteClient, cands: list[dict]) -> tuple[list[dict], list[dict], dict]:
    alive: list[dict] = []
    errored: list[dict] = []
    stats = {"checked": 0, "dead": 0, "errors": 0}

    async def one(e: dict) -> None:
        try:
            data = await client.get_json(probe_url(e["ats"], e["slug"]), use_cache=False, allow_404=True)
        except FetchError:
            stats["errors"] += 1
            errored.append(e)
            return
        finally:
            stats["checked"] += 1
            if stats["checked"] % 500 == 0:
                print(f"[validate] {stats['checked']}/{len(cands)} alive={len(alive)}", file=sys.stderr)
        if data is not None and is_alive(e["ats"], data):
            e["name"] = e["name"] or probe_name(e["ats"], data) or e["slug"]
            alive.append(e)
        else:
            stats["dead"] += 1

    await asyncio.gather(*(one(e) for e in cands))
    return alive, errored, stats


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="validate at most N candidates (testing)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output", default=str(REGISTRY_PATH))
    args = ap.parse_args()

    async with PoliteClient(user_agent=UA, timeout=20, per_host_concurrency=6, min_interval=0.1,
                            retries=2, backoff=2.0) as client:
        cands = list((await gather_candidates(client)).values())
        if args.limit:
            cands = cands[: args.limit]
        print(f"[refresh] {len(cands)} candidates", file=sys.stderr)
        alive, errored, stats = await validate(client, cands)

    # A timeout or 5xx is not proof a board died: keep already-registered boards that errored.
    alive += [e for e in errored if e.get("known")]
    companies = []
    for e in sorted(alive, key=lambda e: (e["ats"], e["slug"].lower())):
        row = {"ats": e["ats"], "slug": e["slug"], "name": e["name"]}
        for k in ("domain", "sector"):
            if e.get(k):
                row[k] = e[k]
        row["sources"] = sorted(e["sources"]) or ["registry"]
        companies.append(row)
    counts = {a: sum(1 for c in companies if c["ats"] == a) for a in ATS}
    doc = {"generated": date.today().isoformat(), "validated_against": "live public ATS APIs",
           "counts": counts, "total": len(companies), "seeds": SEEDS, "companies": companies}
    print(f"[refresh] alive={len(companies)} dead={stats['dead']} errors={stats['errors']} counts={counts}",
          file=sys.stderr)
    if not companies:
        print("[refresh] refusing to write an empty registry", file=sys.stderr)
        return 1
    out_path = Path(args.output)
    try:  # keep the old date when nothing changed so the weekly job makes no empty commits
        old = json.loads(out_path.read_text())
        if old.get("companies") == companies and old.get("seeds") == SEEDS:
            doc["generated"] = old.get("generated", doc["generated"])
    except (OSError, ValueError):
        pass
    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
