# Contributing

This is a **private commercial product**. Contributions are by invitation only.

## Ground rules

- Do not fork this repository to a public account.
- Do not copy source into another public project.
- Do not commit secrets, customer data, resumes, or live Stripe keys.
- Keep changes scoped. Open a pull request against `main` when collaborating.

## Local setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# set SECRET_KEY before running anything beyond localhost experiments
```

## Pull requests

1. Create a feature branch from `main`.
2. Keep commits focused and describe the customer-facing impact.
3. Confirm `.gitignore` still excludes `.env`, `data/*.db`, tokens, and resumes.
4. Request review from `@BenFrohman` (see `CODEOWNERS`).

## License

By contributing, you assign the contribution to Benjamin Frohman and agree it
is covered by the proprietary license in `LICENSE`. Do not submit code you
cannot assign.
