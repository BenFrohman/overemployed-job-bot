# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Polite HTTP: per-host rate limits, conditional requests, retries with backoff.

Every scanner and the company-registry refresher go through PoliteClient so the
bot stays a good citizen of the public job-board APIs it reads:

* per-host concurrency cap and minimum spacing between requests,
* ETag / Last-Modified caching (a 304 reuses the cached body, costs the host little),
* retries with exponential backoff + jitter on timeouts, 429 and 5xx,
  honoring Retry-After,
* no cookies, no auth, no login-walled sites.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}
# Hosts that share one backend (e.g. every <slug>.recruitee.com) share one limit.
SHARED_SUFFIXES = ("recruitee.com", "workable.com", "smartrecruiters.com")


class FetchError(Exception):
    def __init__(self, url: str, status: Optional[int], msg: str = ""):
        super().__init__(f"{url}: {status or ''} {msg}".strip())
        self.url, self.status = url, status


def host_key(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for suffix in SHARED_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    return host


@dataclass
class _Host:
    sem: asyncio.Semaphore
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_at: float = 0.0


@dataclass
class CacheEntry:
    etag: str = ""
    last_modified: str = ""
    data: Any = None


class PoliteClient:
    def __init__(self, *, user_agent: str, timeout: float = 20.0, per_host_concurrency: int = 4,
                 min_interval: float = 0.25, retries: int = 3, backoff: float = 1.0,
                 cache: Optional[dict[str, CacheEntry]] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None,
                 sleep=asyncio.sleep):
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, transport=transport,
                                         headers={"User-Agent": user_agent, "Accept": "application/json"})
        self.per_host_concurrency = per_host_concurrency
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self.cache: dict[str, CacheEntry] = cache if cache is not None else {}
        self._hosts: dict[str, _Host] = {}
        self._sleep = sleep
        self.stats = {"requests": 0, "not_modified": 0, "retries": 0}

    async def __aenter__(self) -> "PoliteClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _host(self, url: str) -> _Host:
        key = host_key(url)
        if key not in self._hosts:
            self._hosts[key] = _Host(asyncio.Semaphore(self.per_host_concurrency))
        return self._hosts[key]

    async def _pace(self, h: _Host) -> None:
        async with h.lock:
            wait = h.next_at - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            h.next_at = max(time.monotonic(), h.next_at) + self.min_interval

    async def get_json(self, url: str, *, use_cache: bool = True, allow_404: bool = False) -> Any:
        """GET JSON. Returns None for a 404 when allow_404; raises FetchError otherwise."""
        h = self._host(url)
        cached = self.cache.get(url) if use_cache else None
        headers = {}
        if cached:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            if attempt:
                self.stats["retries"] += 1
            async with h.sem:
                await self._pace(h)
                self.stats["requests"] += 1
                try:
                    r = await self._client.get(url, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last = FetchError(url, None, type(e).__name__)
                    await self._sleep(self._delay(attempt, None))
                    continue
            if r.status_code == 304 and cached is not None:
                self.stats["not_modified"] += 1
                return cached.data
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in RETRY_STATUSES:
                last = FetchError(url, r.status_code)
                await self._sleep(self._delay(attempt, r.headers.get("Retry-After")))
                continue
            if r.status_code >= 400:
                raise FetchError(url, r.status_code)
            try:
                data = r.json()
            except ValueError as e:
                raise FetchError(url, r.status_code, "invalid JSON") from e
            if use_cache and (r.headers.get("ETag") or r.headers.get("Last-Modified")):
                self.cache[url] = CacheEntry(r.headers.get("ETag", ""), r.headers.get("Last-Modified", ""), data)
            return data
        raise last or FetchError(url, None, "retries exhausted")

    def _delay(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                pass
        return self.backoff * (2 ** attempt) + random.uniform(0, self.backoff / 2)
