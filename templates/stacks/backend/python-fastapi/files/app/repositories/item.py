"""Data-access layer for items.

The repository owns all SQL for a resource and returns ORM objects (or ``None``). It never raises
HTTP errors and holds no business rules — that is the service's job. It ``flush``es (not
``commit``s); the session dependency owns the transaction boundary.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.schemas.item import ItemCreate


class ItemRepository:
    """CRUD data access for :class:`~app.models.item.Item`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session.

        Args:
            session: The active async session for this request.
        """
        self._session = session

    async def list(self) -> Sequence[Item]:
        """Return all items, newest first."""
        result = await self._session.execute(select(Item).order_by(Item.id.desc()))
        return result.scalars().all()

    async def get(self, item_id: int) -> Item | None:
        """Return the item with ``item_id``, or ``None`` if it does not exist."""
        return await self._session.get(Item, item_id)

    async def create(self, data: ItemCreate) -> Item:
        """Insert a new item and return it with server-populated fields loaded."""
        item = Item(title=data.title, description=data.description)
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def delete(self, item: Item) -> None:
        """Delete an existing item."""
        await self._session.delete(item)
        await self._session.flush()
