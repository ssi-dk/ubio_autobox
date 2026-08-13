"""Record start and completion timestamps for each analysis phase."""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, ForeignKey, Integer, String, inspect
from sqlalchemy.types import DateTime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "analysis_phase_events" in inspect(bind).get_table_names():
        return

    op.create_table(
        "analysis_phase_events",
        Column("phase_event_id", String(36), primary_key=True),
        Column(
            "analysis_id",
            String(36),
            ForeignKey("analysis_runs.analysis_id"),
            nullable=False,
        ),
        Column("attempt", Integer, nullable=False),
        Column("phase", String(64), nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True)),
    )
    op.create_index(
        "ix_analysis_phase_events_analysis_id",
        "analysis_phase_events",
        ["analysis_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "analysis_phase_events" not in inspect(bind).get_table_names():
        return
    op.drop_index(
        "ix_analysis_phase_events_analysis_id",
        table_name="analysis_phase_events",
    )
    op.drop_table("analysis_phase_events")
