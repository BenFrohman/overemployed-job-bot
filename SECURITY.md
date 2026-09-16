# Security Policy

## Supported product

This repository contains the proprietary source for **Overemployed-Job Bot**.
Security reports should target the current `main` branch.

## Reporting a vulnerability

Do **not** open a public issue for security findings.

1. Use GitHub **Security Advisories** on this repository (Private vulnerability reporting) if enabled.
2. If advisories are unavailable, contact the owner **@BenFrohman** through a private channel and include:
   - a description of the issue and impact
   - reproduction steps or a proof of concept
   - affected paths, endpoints, or configuration
   - any suggested mitigation

Please allow a reasonable window for investigation before any public disclosure.

## Scope of particular interest

- Authentication and session handling (JWT httpOnly cookies, password hashing)
- Tenant isolation (`user_id` scoping of resumes, preferences, and applications)
- Stripe webhook signature verification and billing unlock state
- Secret handling (`SECRET_KEY`, `ENCRYPTION_KEY`, Stripe keys, OAuth tokens)
- Rate limiting, CSRF, and proxy-header trust (`TRUST_PROXY_HEADERS`)
- Accidental commit of `.env`, `data/credentials.json`, `data/token.json`, or private keys

## Operational expectations

- Keep the repository **private**. Customers do not need GitHub access.
- Never commit live Stripe keys (`sk_live_`, `whsec_`) or private keys.
- Rotate `SECRET_KEY` / `ENCRYPTION_KEY` if they are exposed; existing encrypted blobs will not decrypt with a new key.
- Set a unique production `SECRET_KEY`. Do not ship the `change-me` default.
- Enable GitHub secret scanning, push protection, and Dependabot alerts in repository settings.

## Out of scope

- Findings that require physical access to a developer workstation
- Issues solely in third-party services (Stripe, GitHub, Ollama) with no product-side defect
- Social-engineering reports without a technical vulnerability
