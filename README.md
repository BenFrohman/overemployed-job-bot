# Overemployed-Job Bot

[![ci.yml](https://github.com/BenFrohman/overemployed-job-bot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/BenFrohman/overemployed-job-bot/actions/workflows/ci.yml)

**Developer:** Benjamin Stanley Frohman  
**Status:** Free and open source ([Apache-2.0](LICENSE)). Multi-user web app for remote AI job hunting.

Every signed-in user gets full access. There are no trials, plans, or payments.

Copyright 2026 Benjamin Stanley Frohman. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## Features

1. **Multi-user accounts** — email + password signup/login (bcrypt + JWT httpOnly cookie)
2. **Tenant data model** — applications and preferences scoped by `user_id`; shared job catalog from scanners
3. **Real job scanners** — Remotive, RemoteOK, Arbeitnow, and Greenhouse/Lever/Ashby boards (see below)
4. **Preference filtering** — `/api/jobs` honors each user's keywords and remote-only setting (`?all=true` shows everything)
5. **Public landing page** (`/`) + signed-in app shell (`/app`); admin role for operators
6. **OpSec** — rate limits, encrypted secrets helper, secure cookies flag, audit log

## Job sources

Scanners run every `SCAN_INTERVAL_MINUTES`. Each source has a timeout (`SCAN_TIMEOUT_SECONDS`), a failure in one source never stops the others, listings are normalized and deduplicated, and only roles that look applicable are stored.

| Source | API | Config |
|--------|-----|--------|
| [Remotive](https://remotive.com) | `remotive.com/api/remote-jobs` | `remotive` |
| [RemoteOK](https://remoteok.com) | `remoteok.com/api` (sends a User-Agent) | `remoteok` |
| [Arbeitnow](https://www.arbeitnow.com) | `arbeitnow.com/api/job-board-api` | `arbeitnow` |
| Greenhouse boards | `boards-api.greenhouse.io` | `greenhouse` + `GREENHOUSE_BOARDS` |
| Lever postings | `api.lever.co` | `lever` + `LEVER_COMPANIES` |
| Ashby boards | `api.ashbyhq.com/posting-api` | `ashby` + `ASHBY_BOARDS` |

`SCANNERS_ENABLED` is a comma-separated list of the config names above (all six by default; empty disables scanning). The Greenhouse, Lever, and Ashby slug lists are comma-separated and **empty by default**, so those sources do nothing until you name companies.

**Attribution:** job data from RemoteOK is provided by [Remote OK](https://remoteok.com). Every RemoteOK listing links back to its remoteok.com page, as RemoteOK's API terms require. Listing content belongs to its source and the posting employer.

## Repository layout

| Path | Purpose |
|------|--------|
| `run.py` | Process entry point |
| `app/` | Application package (auth, security, scanners, persistence) |
| `scripts/` | Operator helpers |
| `.github/workflows/ci.yml` | Import and secret-hygiene checks |
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
