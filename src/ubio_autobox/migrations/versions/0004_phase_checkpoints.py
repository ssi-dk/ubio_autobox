"""Add explicit phase status and checkpoint metadata."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, MetaData, String, Table, Text, inspect, update
from sqlalchemy.types import DateTime

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {
        item["name"] for item in inspect(bind).get_columns("analysis_phase_events")
    }
    if "status" not in existing:
        op.add_column(
            "analysis_phase_events",
            Column("status", String(16), nullable=True),
        )
    if "checkpoint_uri" not in existing:
        op.add_column(
            "analysis_phase_events",
            Column("checkpoint_uri", Text()),
        )
    if "checkpoint_sha256" not in existing:
        op.add_column(
            "analysis_phase_events",
            Column("checkpoint_sha256", String(64)),
        )
    if "error_summary" not in existing:
        op.add_column(
            "analysis_phase_events",
            Column("error_summary", Text()),
        )

    events = Table(
        "analysis_phase_events",
        MetaData(),
        Column("status", String(16)),
        Column("completed_at", DateTime(timezone=True)),
    )
    bind.execute(
        update(events).where(events.c.status.is_(None)).values(status="succeeded")
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {
        item["name"] for item in inspect(bind).get_columns("analysis_phase_events")
    }
    for name in ("error_summary", "checkpoint_sha256", "checkpoint_uri", "status"):
        if name in existing:
            op.drop_column("analysis_phase_events", name)
