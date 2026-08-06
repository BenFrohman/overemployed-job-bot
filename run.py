#!/usr/bin/env python3
"""
Overemployed-Job Bot – entry point.
Developer: Benjamin Frohman

Usage:
  1. cp .env.example .env   and set SECRET_KEY (+ Stripe keys for production)
  2. ollama serve && ollama pull llama3.1:8b
  3. playwright install chromium
  4. python run.py

Open http://127.0.0.1:8743 → Start free 24h trial → $20 lifetime via Stripe.
"""
import asyncio
import os
import uvicorn
from app.config import get_settings
from app.database import init_db
from app.scheduler import start_scheduler, run_scan_cycle

settings = get_settings()


async def _initial_scan():
    print("[run] Performing initial scan in background...")
    try:
        await run_scan_cycle()
    except Exception as e:
        print(f"[run] Initial scan failed (will retry on schedule): {e}")


async def main():
    await init_db()
    print("[run] Database initialized (multi-tenant).")
    if settings.secret_key.startswith("change-me"):
        print("[run] WARNING: set a strong SECRET_KEY in .env before production.")

    start_scheduler()
    asyncio.create_task(_initial_scan())

    config = uvicorn.Config(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    asyncio.run(main())
