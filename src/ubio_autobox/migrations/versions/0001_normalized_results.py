"""Create normalized identity, provenance, and scientific result tables.

Revision ID: 0001
Revises:
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op

from ubio_autobox.persistence import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
