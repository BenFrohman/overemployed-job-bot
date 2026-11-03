# Copyright 2026 Benjamin Stanley Frohman. Licensed under the Apache License, Version 2.0.
"""Async database setup."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import get_settings
from app.models import Base

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def _add_missing_columns(conn) -> None:
    """Tiny forward-only migration: add new nullable/defaulted columns to existing tables."""
    from sqlalchemy import inspect

    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have or col.primary_key:
                continue
            ddl = col.type.compile(dialect=conn.dialect)
            default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
            clause = ""
            if isinstance(default, bool):
                clause = f" DEFAULT {int(default)}"
            elif isinstance(default, (int, float)):
                clause = f" DEFAULT {default}"
            elif isinstance(default, str):
                clause = " DEFAULT '" + default.replace("'", "''") + "'"
            conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{clause}')


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
