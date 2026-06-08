"""Pydantic v2 schemas for the ``Item`` resource.

Schemas are the API contract and are intentionally decoupled from the ORM model: ``ItemCreate`` is
the request body, ``ItemRead`` is the response (``from_attributes`` lets it be built from an ORM
object via :meth:`ItemRead.model_validate`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    """Fields shared by item requests."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ItemCreate(ItemBase):
    """Request body for creating an item."""


class ItemRead(ItemBase):
    """Response model for an item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
