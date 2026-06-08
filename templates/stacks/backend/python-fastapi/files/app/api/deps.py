"""Reusable FastAPI dependencies.

Wires the request-scoped session into repositories and services. Routers depend on
``ItemServiceDep`` and stay ignorant of how the service is constructed — swap implementations or
add caching here without touching route code.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.item import ItemRepository
from app.services.item import ItemService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_item_service(session: SessionDep) -> ItemService:
    """Build an :class:`~app.services.item.ItemService` for the current request.

    Args:
        session: The request-scoped async session (injected).

    Returns:
        A service wired to a repository bound to ``session``.
    """
    return ItemService(ItemRepository(session))


ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]
