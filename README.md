# Overemployed-Job Bot

[![ci.yml](https://github.com/BenFrohman/overemployed-job-bot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/BenFrohman/overemployed-job-bot/actions/workflows/ci.yml)

**Developer:** Benjamin Stanley Frohman  
**Status:** Free and open source ([Apache-2.0](LICENSE)). A multi-user job finder that matches people to work that fits their skills **and** their purpose.

Every signed-in user gets full access. There are no trials, plans, or payments.

Copyright 2026 Benjamin Stanley Frohman. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## Features

1. **Every company we can verify** — `data/companies.json` lists **9,113** employers whose public job boards answered their live API on 2026-11-03, refreshed weekly
2. **10 job sources** — Remotive, RemoteOK, Arbeitnow, Hacker News "Who is hiring", and six applicant-tracking systems (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee)
3. **Polite at scale** — concurrent fetching with per-host limits, ETag / If-Modified-Since caching, retries with backoff that honor `Retry-After`, and rotation so one full sweep is spread across many cycles
4. **Purpose matching** — a profile of skills, experience, values, causes, desired impact, location, remote preference and pay floor; free local ranking; a plain-language "why this fits you" on every match; save/dismiss feedback tunes the ranking
5. **Multi-user accounts** — bcrypt + JWT httpOnly cookie; profiles, feedback and applications are scoped per user; admin role for operators
6. **OpSec** — rate limits (including on matching), encrypted secrets helper, secure cookies, audit log, no secrets in the repo, and no scraping of login-walled sites (no LinkedIn or Indeed)

## Company registry

| ATS | Live boards |
|-----|------------:|
| greenhouse | 4,458 |
| lever | 2,040 |
| ashby | 2,609 |
| workable | 5 |
| smartrecruiters | 1 |
| recruitee | 0 |
| **Total** | **9,113** |

Counts are real: `scripts/refresh_companies.py` probes every candidate against its ATS's public API and drops boards that are gone. A timeout or 5xx is not treated as proof a board died, so already-listed boards survive a flaky week. SmartRecruiters answers `200` even for companies that don't exist, so a SmartRecruiters board only counts as live if it currently lists at least one job.

Workable, SmartRecruiters and Recruitee are underrepresented: we found no openly licensed directory of their boards, so they come only from the small MIT-licensed seed below plus anything you add with `WORKABLE_ACCOUNTS`, `SMARTRECRUITERS_COMPANIES` or `RECRUITEE_COMPANIES`. Pull requests that add verified slugs are welcome.

The workflow `.github/workflows/refresh-companies.yml` reruns the refresher every Monday and commits `data/companies.json` only if it changed. Only that job has `contents: write`.

### Registry seeds and licenses

| Seed | License | Use |
|------|---------|-----|
| [LastRound AI ATS company directory](https://github.com/fyrosofttech/lastroundai-hiring-data) (Aug 2026) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | Greenhouse, Lever and Ashby slugs. Data from LastRound AI, [lastroundai.com/blog/salary-transparency-study-2026](https://lastroundai.com/blog/salary-transparency-study-2026). |
| [Africa ATS Directory](https://github.com/Thelastpoet/africa-ats-directory) | MIT | Slugs and sectors for all six ATSs |

Datasets under non-commercial licenses (CC BY-NC) were deliberately left out because they conflict with Apache-2.0. Only slugs, names and sectors are taken; job content is always fetched live from the employer's board.

## Job sources

| Source | API | Config |
|--------|-----|--------|
| [Remotive](https://remotive.com) | `remotive.com/api/remote-jobs` | `remotive` |
| [RemoteOK](https://remoteok.com) | `remoteok.com/api` (sends a User-Agent) | `remoteok` |
| [Arbeitnow](https://www.arbeitnow.com) | `arbeitnow.com/api/job-board-api` | `arbeitnow` |
| [Hacker News](https://news.ycombinator.com) "Who is hiring" | `hn.algolia.com/api/v1` (latest monthly thread) | `hn` |
| Greenhouse | `boards-api.greenhouse.io` | `greenhouse` + `GREENHOUSE_BOARDS` |
| Lever | `api.lever.co` | `lever` + `LEVER_COMPANIES` |
| Ashby | `api.ashbyhq.com/posting-api` | `ashby` + `ASHBY_BOARDS` |
| Workable | `apply.workable.com/api/v1/widget` | `workable` + `WORKABLE_ACCOUNTS` |
| SmartRecruiters | `api.smartrecruiters.com/v1` | `smartrecruiters` + `SMARTRECRUITERS_COMPANIES` |
| Recruitee | `{slug}.recruitee.com/api/offers` | `recruitee` + `RECRUITEE_COMPANIES` |

`SCANNERS_ENABLED` lists the sources to run (all ten by default; empty disables scanning). With `USE_COMPANY_REGISTRY=true` (the default) the ATS scanners cover every registry company plus any extra slugs. Each cycle fetches the feeds and the next `BOARDS_PER_CYCLE` boards (default 300); a cursor stored in the database picks up where the last cycle stopped. Requests share one client that allows `PER_HOST_CONCURRENCY` requests per host, spaces them by `PER_HOST_MIN_INTERVAL_SECONDS`, and retries 429/5xx up to `HTTP_RETRIES` times. A failure in one board never stops the others. Listings are normalized and deduplicated, still-open listings get their `last_seen_at` refreshed, and listings unseen for `JOB_RETENTION_DAYS` are pruned unless someone saved or applied to them. `CATALOG_FILTER=applicable` brings back the old non-engineering-only filter.

**Attribution:** job data from RemoteOK is provided by [Remote OK](https://remoteok.com). Every RemoteOK listing links back to its remoteok.com page, as RemoteOK's API terms require. Hacker News listings link to their comment. Listing content belongs to its source and the posting employer.

## How matching works

Matching runs on your own server, free and with no outside AI service:

1. **Skills fit (45%)**: BM25 relevance of your skills and experience against each listing.
2. **Mission fit (35%)**: your causes (mapped to a 13-cause vocabulary, e.g. climate, health, education, AI safety), values and desired impact, matched against the listing text and the company's sector.
3. **Preferences (20%)**: remote/hybrid/onsite and location, plus pay. Listings that state pay under your floor are scored down and the explanation says so. `remote` is a hard filter.
4. **Your feedback**: jobs you dismiss are hidden, and listings similar to ones you saved (or unlike ones you dismissed) move up (a bonus of up to 15%).

Each match comes with a score breakdown and a plain-language "why this fits you", e.g. *"Uses your skills in python, data pipelines. SolarGrid (Climate) works on climate, a cause you care about. It's remote, as you prefer. Listed pay (150,000–180,000) meets your 120,000 floor."*

Optional: install `sentence-transformers` and set `MATCH_EMBEDDINGS=true` to blend in local semantic similarity (`EMBEDDING_MODEL`, default `all-MiniLM-L6-v2`). It is off by default.

| Endpoint | Purpose |
|----------|---------|
| `GET/PUT /api/profile` | Your purpose profile |
| `GET /api/matches?limit=20` | Ranked matches with `why`, `reasons` and `breakdown` (rate-limited per user) |
| `POST /api/matches/{job_id}/feedback` | `{"action": "save" | "dismiss" | "clear"}`; save also tracks it under applications |

## Repository layout

| Path | Purpose |
|------|--------|
| `run.py` | Process entry point |
| `app/` | Application package (auth, security, scanners, persistence) |
| `scripts/` | Operator helpers |
| `data/companies.json` | Verified company registry |
| `.github/workflows/ci.yml` | Import checks, tests and secret-hygiene checks |
| `.github/workflows/refresh-companies.yml` | Weekly registry refresh |
| `.env.example` | Required environment template (copy to `.env`) |
| `SECURITY.md` | Vulnerability reporting |
| `CODEOWNERS` | Default reviewer `@BenFrohman` |

## Quick start (local)

```bash
cd overemployed-job-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# set SECRET_KEY; optionally set SCANNERS_ENABLED and board slugs
ollama serve && ollama pull llama3.1:8b
python run.py
```

Open **http://127.0.0.1:8743**, sign up, and set your preferences. Run the tests with `python -m pytest -q tests` (HTTP is mocked; no network needed).

### Required configuration

| Variable | Notes |
|----------|--------|
| `SECRET_KEY` | Required. Do not leave the `change-me` default in production. |
| `ENCRYPTION_KEY` | Optional Fernet key. If unset, derived from `SECRET_KEY`. |
| `DATABASE_URL` | Defaults to local SQLite under `data/`. |
| `SCANNERS_ENABLED` | Comma-separated sources to run (see Job sources). |
| `GREENHOUSE_BOARDS` / `LEVER_COMPANIES` / `ASHBY_BOARDS` | Comma-separated company slugs; empty by default. |
| `TRUST_PROXY_HEADERS` | Enable only behind a trusted reverse proxy. |

Never commit `.env`, `data/credentials.json`, `data/token.json`, private keys, user resumes, or API keys.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Copyright 2026 Benjamin Stanley Frohman.

You may use, modify, and redistribute this code under that license; see [`NOTICE`](NOTICE) for attributions. Third-party packages in `requirements.txt` keep their own licenses. Contributions are accepted under the same license ([`CONTRIBUTING.md`](CONTRIBUTING.md)).

## Security and protections

- Policy: [`SECURITY.md`](SECURITY.md)
- Code owners: [`CODEOWNERS`](CODEOWNERS)
- Dependency updates: [`.github/dependabot.yml`](.github/dependabot.yml)
- CI secret hygiene: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

Enable the following in GitHub if they are not already on:

1. Rulesets protecting `main` and tags (no deletion, no force-push)
2. Push restriction on secret-like paths (`.env`, credentials, keys)
3. Secret scanning + push protection
4. Dependabot alerts and security updates
5. Private vulnerability reporting

## Engineering note

Earlier commits held only a skeleton: CI imported `app.config`, `app.models`, `app.main`, `app.scheduler`, and `app.auth.rbac`, but several of those modules had never been committed. They were newly implemented on **Nov 3, 2026** (they are not a recovered original), along with the job scanners and the test suite, and the paid billing layer was removed when the project became free.

## Citation

Cite this work with [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository" button).
