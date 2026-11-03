# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Role-based access control and tenant scoping."""
from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Any, Optional

from fastapi import HTTPException, Request, status


class Role(str, Enum):
    ANONYMOUS = "anonymous"
    USER = "user"
    ADMIN = "admin"


class Permission(str, Enum):
    VIEW_JOBS = "view_jobs"
    MANAGE_OWN_APPLICATIONS = "manage_own_applications"
    MANAGE_OWN_PREFERENCES = "manage_own_preferences"
    VIEW_ALL_USERS = "view_all_users"
    VIEW_AUDIT_LOG = "view_audit_log"
    RUN_SCANS = "run_scans"


_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ANONYMOUS: frozenset(),
    Role.USER: frozenset({Permission.VIEW_JOBS, Permission.MANAGE_OWN_APPLICATIONS,
                          Permission.MANAGE_OWN_PREFERENCES}),
    Role.ADMIN: frozenset(Permission),
}


def role_from_user(user: Any) -> Role:
    if user is None:
        return Role.ANONYMOUS
    return Role.ADMIN if getattr(user, "is_admin", False) else Role.USER


def has_permission(user: Any, permission: Permission) -> bool:
    return permission in _ROLE_PERMISSIONS[role_from_user(user)]


def _current_user(request: Request):
    return getattr(request.state, "user", None)


def require_authenticated(request: Request):
    user = _current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return user


def require_admin(request: Request):
    user = require_authenticated(request)
    if role_from_user(user) is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


def require_permission(permission: Permission):
    """Use as a FastAPI dependency: Depends(require_permission(Permission.X))."""
    def dependency(request: Request):
        user = require_authenticated(request)
        if not has_permission(user, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission.value}")
        return user
    return dependency


def assert_own_resource(user: Any, owner_id: Optional[int]) -> None:
    if role_from_user(user) is Role.ADMIN:
        return
    if user is None or owner_id != getattr(user, "id", None):
        # 404 rather than 403 so other tenants' ids are not disclosed
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def scope_user_id(user: Any, requested_user_id: Optional[int] = None) -> int:
    """Return the user_id a query must be scoped to. Only admins may look at others."""
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    if requested_user_id is None or requested_user_id == user.id:
        return user.id
    if role_from_user(user) is Role.ADMIN:
        return requested_user_id
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot access another user's data")
