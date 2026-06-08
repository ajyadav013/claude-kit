"""Async database engine and the request-scoped session dependency.

The engine is created at import time but does not connect until first use, so importing this
module is cheap and side-effect-free for tooling and tests (tests override :func:`get_session`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False, future=True)
async_session_factory = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped async session, committing on success and rolling back on error.

    Yields:
        An :class:`~sqlalchemy.ext.asyncio.AsyncSession` bound to a single request. The session
        is committed after the request handler returns successfully, or rolled back if it raised.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
