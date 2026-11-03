#!/usr/bin/env bash
# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v gh >/dev/null || ! gh auth status >/dev/null 2>&1; then
  echo "Authenticate first: gh auth login"
  exit 1
fi
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/BenFrohman/overemployed-job-bot.git
git push -u origin main --force-with-lease
echo "Pushed → https://github.com/BenFrohman/overemployed-job-bot"
