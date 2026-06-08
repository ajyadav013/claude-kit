"""Business logic for items.

Services orchestrate repositories and enforce rules, raising **domain** exceptions (e.g.
:class:`ItemNotFoundError`). Routers translate those into HTTP responses — the service itself
stays transport-agnostic and unit-testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.item import Item
from app.repositories.item import ItemRepository
from app.schemas.item import ItemCreate


class ItemNotFoundError(Exception):
    """Raised when an item does not exist."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} not found")
        self.item_id = item_id


class ItemService:
    """Business operations for items."""

    def __init__(self, repository: ItemRepository) -> None:
        """Inject the repository this service depends on.

        Args:
            repository: The item data-access repository.
        """
        self._repository = repository

    async def list_items(self) -> Sequence[Item]:
        """Return all items."""
        return await self._repository.list()

    async def create_item(self, data: ItemCreate) -> Item:
        """Create and return a new item."""
        return await self._repository.create(data)

    async def get_item(self, item_id: int) -> Item:
        """Return an item by id.

        Raises:
            ItemNotFoundError: If no item has ``item_id``.
        """
        item = await self._repository.get(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        return item

    async def delete_item(self, item_id: int) -> None:
        """Delete an item by id.

        Raises:
            ItemNotFoundError: If no item has ``item_id``.
        """
        item = await self.get_item(item_id)
        await self._repository.delete(item)
