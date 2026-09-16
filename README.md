# Overemployed-Job Bot

**Developer:** Benjamin Frohman  
**Status:** Proprietary commercial product — multi-tenant SaaS for remote AI job hunting.

| Plan | Detail |
|------|--------|
| Trial | **24 hours** free after signup |
| Unlock | **$20 one-time** lifetime access (Stripe Checkout) |
| Privacy | Per-user sandbox (resume, prefs, applications) |

Copyright (c) 2026 Benjamin Frohman. All rights reserved. See [`LICENSE`](LICENSE), [`COPYRIGHT`](COPYRIGHT), and [`NOTICE`](NOTICE).

## Visibility and source control

This product is **not** open source. The repository must remain **private**.

- Only invited collaborators should see the source.
- Customers use the hosted application; they do not need GitHub access.
- If GitHub shows this repository as **public**, change visibility immediately:  
  **Settings → General → Danger Zone → Change repository visibility → Private**.
- Disable forking while the product remains closed-source.

Rulesets live at [Settings → Rules](https://github.com/BenFrohman/overemployed-job-bot/settings/rules).

## Features (SaaS core)

1. **Multi-user accounts** — email + password signup/login (bcrypt + JWT httpOnly cookie)
2. **Tenant data model** — applications and preferences scoped by `user_id`; shared job catalog from scanners
3. **Trial + Stripe $20 lifetime** — webhook-verified unlock; cards never touch our servers
4. **Public marketing page** (`/`) + private app shell (`/app`)
5. **OpSec** — rate limits, encrypted secrets helper, secure cookies flag, audit log, webhook signatures

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
# set SECRET_KEY; optional Stripe keys for billing
ollama serve && ollama pull llama3.1:8b
python run.py
```

Open **http://127.0.0.1:8743** — start the 24-hour trial, then unlock lifetime access via Stripe (or use the localhost dev unlock).

### Required configuration

| Variable | Notes |
|----------|--------|
| `SECRET_KEY` | Required. Do not leave the `change-me` default in production. |
| `ENCRYPTION_KEY` | Optional Fernet key. If unset, derived from `SECRET_KEY`. |
| `DATABASE_URL` | Defaults to local SQLite under `data/`. |
| `STRIPE_PRICE_LIFETIME_CENTS` | Must remain `2000` for the $20 lifetime plan. |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Production billing only. |
| `TRUST_PROXY_HEADERS` | Enable only behind a trusted reverse proxy. |

Never commit `.env`, `data/credentials.json`, `data/token.json`, private keys, customer resumes, or live Stripe secrets.

## License and copyright

This repository is licensed under the proprietary terms in [`LICENSE`](LICENSE). All rights are reserved by **Benjamin Frohman**.

- No right to copy, fork publicly, redistribute, or create derivative products is granted by access to this repository.
- Third-party packages in `requirements.txt` keep their own licenses; those licenses do not cover this application.
- Invited contributors assign their work to the copyright holder as described in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security and protections

- Policy: [`SECURITY.md`](SECURITY.md)
- Code owners: [`CODEOWNERS`](CODEOWNERS)
- Dependency updates: [`.github/dependabot.yml`](.github/dependabot.yml)
- CI secret hygiene: [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

Enable the following in GitHub if they are not already on:

1. Repository visibility = **Private**
2. Rulesets protecting `main` and tags (no deletion, no force-push)
3. Push restriction on secret-like paths (`.env`, credentials, keys)
4. Secret scanning + push protection
5. Dependabot alerts and security updates
6. Private vulnerability reporting

## Current engineering note

The committed tree is still a **skeleton** relative to what CI imports (`app.config`, `app.models`, `app.main`, `app.billing`, `app.scheduler`, `app.auth.rbac`). Governance and protection files are in place; application modules that are not yet in git will need to be added before CI can pass end-to-end.
