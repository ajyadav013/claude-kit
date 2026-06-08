"""Test fixtures: an isolated in-memory database and an HTTP client.

Tests run against an in-memory SQLite database (via ``aiosqlite``), so the suite needs **no
Postgres** and no network. A ``StaticPool`` keeps a single underlying connection alive for the
test's lifetime — without it, each new connection would get a *fresh* in-memory database and the
schema created in one would be invisible to the next. The ``get_session`` dependency is overridden
so the app uses this test database instead of the configured Postgres engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models.item import Item  # noqa: F401  (registers the table on Base.metadata)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Yield an :class:`httpx.AsyncClient` bound to the app with a fresh test database."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()
