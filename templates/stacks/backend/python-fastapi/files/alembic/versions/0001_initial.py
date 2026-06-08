"""initial items table

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00

Hand-written initial migration so ``alembic upgrade head`` produces a working schema out of the
box. Regenerate subsequent migrations with ``alembic revision --autogenerate -m "<message>"``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``items`` table."""
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_items_title", "items", ["title"], unique=False)


def downgrade() -> None:
    """Drop the ``items`` table."""
    op.drop_index("ix_items_title", table_name="items")
    op.drop_table("items")
