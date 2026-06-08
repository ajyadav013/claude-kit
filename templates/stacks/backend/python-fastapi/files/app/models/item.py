"""The ``Item`` ORM model — the example resource for the vertical slice.

Copy this file as the starting point for a new resource: rename the class and ``__tablename__``,
adjust columns, then generate an Alembic migration.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Item(Base):
    """A single item record."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
