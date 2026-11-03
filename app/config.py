# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Overemployed-Job Bot"
    app_host: str = "127.0.0.1"
    app_port: int = 8743
    base_url: str = "http://127.0.0.1:8743"

    secret_key: str = "change-me-generate-a-long-random-value"
    encryption_key: str = ""
    jwt_algorithm: str = "HS256"
    session_hours: int = 24 * 7
    session_cookie_name: str = "ojb_session"
    secure_cookies: bool = False
    trust_proxy_headers: bool = False

    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    trial_hours: int = 24
    stripe_price_lifetime_cents: int = 2000
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""

    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300

    scan_interval_minutes: int = 60

    google_client_id: str = ""
    google_client_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
