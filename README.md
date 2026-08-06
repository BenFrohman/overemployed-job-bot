# Overemployed-Job Bot

**Developer:** Benjamin Frohman  
**Private commercial product** — multi-tenant SaaS for remote AI job hunting.

| Plan | Detail |
|------|--------|
| Trial | **24 hours** free after signup |
| Unlock | **$20 one-time** lifetime access (Stripe Checkout) |
| Privacy | Per-user sandbox (resume, prefs, applications) |

## Why private on GitHub?

This is a **product you sell**, not an open-source giveaway. A **private** repo means:

- Only people you invite can see the source
- Still get Actions CI, issues, PRs, releases
- Customers **do not** need GitHub access — they use your hosted URL

Public repos are for free/open collaboration. Keep this **private** unless you intentionally open-source it.

Repo: `https://github.com/BenFrohman/overemployed-job-bot` (private)

## Features (SaaS core)

1. **Multi-user accounts** — email + password signup/login (bcrypt + JWT httpOnly cookie)
2. **Tenant data model** — applications & prefs scoped by `user_id`; shared job catalog from scanners
3. **Trial + Stripe $20 lifetime** — webhook-verified unlock; cards never touch our servers
4. **Public marketing page** (`/`) + private app shell (`/app`)
5. **OpSec** — rate limits, encrypted secrets helper, secure cookies flag, audit log, webhook signatures

## Quick start (local)

```bash
cd overemployed-job-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# set SECRET_KEY; optional Stripe keys
ollama serve && ollama pull llama3.1:8b
python run.py
```

Open **http://127.0.0.1:8743** — Start free 24h trial → $20 lifetime via Stripe (or Dev unlock on localhost).

Proprietary. All rights reserved by **Benjamin Frohman**.
