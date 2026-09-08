# Auth + Preferences integration

## 1. Middleware (main.py)

```python
from app.auth.deps import AuthUserMiddleware
from app.preferences import router as preferences_router

app.add_middleware(AuthUserMiddleware)
app.include_router(preferences_router)
```

When issuing JWTs on login, set `sub` to the user email **lowercased** or the numeric user id.

## 2. Protect routes

```python
from app.auth import require_authenticated, require_admin, assert_own_resource, scope_user_id

@app.get("/api/me")
async def me(request: Request):
    user = require_authenticated(request)
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}

@app.get("/api/jobs")
async def jobs(request: Request, user_id: int | None = None):
    user = require_authenticated(request)
    uid = scope_user_id(user, user_id)
    ...
```

## 3. Preferences UI
Each logged-in user sets their own field/keywords at `/settings` or via POST `/api/preferences`.
No field is pre-assigned. Ashley and future users choose for themselves.
