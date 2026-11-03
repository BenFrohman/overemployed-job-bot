# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Test env: isolated temp SQLite DB, no scanners or network unless a test opts in."""
import os
import tempfile

os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["SCANNERS_ENABLED"] = ""

import asyncio  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Give every test empty tables so results don't depend on test order."""
    from app.database import engine
    from app.models import Base

    async def reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(reset())
    yield
