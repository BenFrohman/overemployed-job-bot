"""OpSec helpers: rate limiting, secret encryption, request hardening."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class RateLimiter:
    """In-memory sliding-window rate limiter (per process)."""

    def __init__(self) -> None:
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            cutoff = now - window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def remaining(self, key: str, limit: int, window_seconds: float) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            cutoff = now - window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            return max(0, limit - len(q))


rate_limiter = RateLimiter()


def client_ip(request) -> str:
    settings = get_settings()
    if settings.trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _fernet() -> Fernet:
    settings = get_settings()
    raw = (settings.encryption_key or "").strip()
    if not raw:
        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        import base64
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)
    if len(raw) == 44 and raw.endswith("="):
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            pass
    import base64
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    if plaintext is None:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Could not decrypt secret — wrong ENCRYPTION_KEY or corrupt data") from e


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a or "", b or "")
