# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""Middleware that resolves the session cookie into request.state.user."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.tokens import decode_session_token
from app.config import get_settings


class AuthUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        from app.database import AsyncSessionLocal
        from app.models import User

        request.state.user = None
        token = request.cookies.get(get_settings().session_cookie_name, "")
        uid = decode_session_token(token)
        if uid is not None:
            async with AsyncSessionLocal() as db:
                request.state.user = await db.get(User, uid)
        return await call_next(request)
