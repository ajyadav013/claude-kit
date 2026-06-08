"""Declarative base for all ORM models.

Every model subclasses :class:`Base`. Import models before calling ``Base.metadata.create_all``
or running Alembic autogenerate so their tables are registered on the shared metadata.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base."""
