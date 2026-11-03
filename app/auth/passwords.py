# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""bcrypt password hashing."""
import bcrypt


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    # bcrypt only uses the first 72 bytes; reject longer input instead of silently truncating
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    raw = password.encode("utf-8")
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except ValueError:
        return False
