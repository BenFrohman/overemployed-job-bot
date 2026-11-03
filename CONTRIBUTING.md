<!-- Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0. -->
# Contributing

Overemployed-Job Bot is free and open source under the Apache License 2.0. Issues and pull requests are welcome.

## Ground rules

- Do not commit secrets, user data, resumes, or API keys.
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
2. Keep commits focused and describe the user-facing impact.
3. Run `python -m pytest -q tests` (tests must not hit the network; mock HTTP).
4. Confirm `.gitignore` still excludes `.env`, `data/*.db`, tokens, and resumes.
5. Request review from `@BenFrohman` (see `CODEOWNERS`).

## License

By contributing, you agree your contribution is licensed under the Apache License,
Version 2.0 (see `LICENSE`), as described in section 5 of that license.
