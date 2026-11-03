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
    # Comma-separated sources (empty = none):
    # remotive,remoteok,arbeitnow,hn,greenhouse,lever,ashby,workable,smartrecruiters,recruitee
    scanners_enabled: str = "remotive,remoteok,arbeitnow,hn,greenhouse,lever,ashby,workable,smartrecruiters,recruitee"
    # Use data/companies.json (validated company boards) for the ATS sources.
    use_company_registry: bool = True
    # Extra comma-separated board slugs on top of the registry, e.g. "anthropic,openai".
    greenhouse_boards: str = ""
    lever_companies: str = ""
    ashby_boards: str = ""
    workable_accounts: str = ""
    smartrecruiters_companies: str = ""
    recruitee_companies: str = ""
    # Rotation: how many registry boards each cycle visits; a full sweep spreads over many cycles.
    boards_per_cycle: int = 300
    per_host_concurrency: int = 4
    per_host_min_interval_seconds: float = 0.25
    http_retries: int = 3
    # "all" keeps every listing (matching ranks them); "applicable" keeps the legacy
    # non-engineering/remote filter from app.scanner.base.looks_applicable.
    catalog_filter: str = "all"
    job_retention_days: int = 45
    # Optional local sentence-embedding model (needs `pip install sentence-transformers`).
    match_embeddings: bool = False
    embedding_model: str = "all-MiniLM-L6-v2"
    match_rate_limit: int = 60
    scanner_user_agent: str = "overemployed-job-bot/1.0 (+https://github.com/BenFrohman/overemployed-job-bot)"

    def csv_list(self, value: str) -> list[str]:
        return [v.strip() for v in value.split(",") if v.strip()]

    google_client_id: str = ""
    google_client_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
