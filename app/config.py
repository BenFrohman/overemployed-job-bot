# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
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


    login_rate_limit: int = 10
    login_rate_window_seconds: int = 300

    scan_interval_minutes: int = 60
    scan_timeout_seconds: float = 20.0
    # Comma-separated: remotive,remoteok,arbeitnow,greenhouse,lever,ashby (empty = none)
    scanners_enabled: str = "remotive,remoteok,arbeitnow,greenhouse,lever,ashby"
    # Comma-separated public job-board slugs, e.g. "anthropic,openai" (empty by default)
    greenhouse_boards: str = ""
    lever_companies: str = ""
    ashby_boards: str = ""
    scanner_user_agent: str = "overemployed-job-bot/1.0 (+https://github.com/BenFrohman/overemployed-job-bot)"

    def csv_list(self, value: str) -> list[str]:
        return [v.strip().lower() for v in value.split(",") if v.strip()]

    google_client_id: str = ""
    google_client_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
