"""HTTP routes for the ``Item`` resource.

Routers are thin: validate input via schemas, delegate to the service, and translate domain
errors into HTTP responses. No business logic or SQL belongs here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ItemServiceDep
from app.schemas.item import ItemCreate, ItemRead
from app.services.item import ItemNotFoundError

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemRead], summary="List items")
async def list_items(service: ItemServiceDep) -> list[ItemRead]:
    """Return all items, newest first."""
    items = await service.list_items()
    return [ItemRead.model_validate(item) for item in items]


@router.post(
    "",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an item",
)
async def create_item(payload: ItemCreate, service: ItemServiceDep) -> ItemRead:
    """Create a new item and return it."""
    item = await service.create_item(payload)
    return ItemRead.model_validate(item)


@router.get("/{item_id}", response_model=ItemRead, summary="Get an item")
async def get_item(item_id: int, service: ItemServiceDep) -> ItemRead:
    """Return a single item by id.

    Raises:
        HTTPException: 404 if the item does not exist.
    """
    try:
        item = await service.get_item(item_id)
    except ItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="item not found"
        ) from exc
    return ItemRead.model_validate(item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an item",
)
async def delete_item(item_id: int, service: ItemServiceDep) -> None:
    """Delete an item by id.

    Raises:
        HTTPException: 404 if the item does not exist.
    """
    try:
        await service.delete_item(item_id)
    except ItemNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="item not found"
        ) from exc
