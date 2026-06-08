"""Tests for the items CRUD endpoints — the vertical-slice example."""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_then_list_item(client: AsyncClient) -> None:
    """Creating an item returns 201 and the item appears in the listing."""
    created = await client.post(
        "/items", json={"title": "First", "description": "hello"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "First"
    assert body["description"] == "hello"
    assert isinstance(body["id"], int)
    assert "created_at" in body

    listing = await client.get("/items")
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["title"] == "First"


async def test_create_rejects_blank_title(client: AsyncClient) -> None:
    """A blank title fails schema validation with 422."""
    response = await client.post("/items", json={"title": ""})
    assert response.status_code == 422


async def test_get_missing_item_returns_404(client: AsyncClient) -> None:
    """Fetching an unknown id returns 404."""
    response = await client.get("/items/999")
    assert response.status_code == 404


async def test_delete_item(client: AsyncClient) -> None:
    """Deleting an item returns 204 and the item is then gone."""
    created = await client.post("/items", json={"title": "Temp"})
    item_id = created.json()["id"]

    deleted = await client.delete(f"/items/{item_id}")
    assert deleted.status_code == 204

    after = await client.get(f"/items/{item_id}")
    assert after.status_code == 404
