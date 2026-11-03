# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""JWT session tokens (sub = numeric user id)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config import get_settings


def create_session_token(user_id: int) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": int(now.timestamp()),
               "exp": int((now + timedelta(hours=s.session_hours)).timestamp())}
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_session_token(token: str) -> Optional[int]:
    if not token:
        return None
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError):
        return None
