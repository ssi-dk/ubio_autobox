"""Add analysis phase, workspace, and retry-history observability."""

from __future__ import annotations

from typing import Any

from alembic import op
from sqlalchemy import JSON, Column, String, Text, inspect
from sqlalchemy.types import DateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _add_if_missing(column: Column[Any]) -> None:
    bind = op.get_bind()
    existing = {item["name"] for item in inspect(bind).get_columns("analysis_runs")}
    if column.name not in existing:
        op.add_column("analysis_runs", column)


def _column(name: str, column_type: Any) -> Column[Any]:
    return Column(name, column_type)


def upgrade() -> None:
    # 0001 creates tables from the current model metadata, so fresh databases
    # may already contain these columns. Existing installations do not.
    _add_if_missing(_column("execution_phase", String(64)))
    _add_if_missing(_column("phase_updated_at", DateTime(timezone=True)))
    _add_if_missing(_column("attempt_workspace_uri", Text()))
    _add_if_missing(_column("failed_workspace_uri", Text()))
    _add_if_missing(_column("attempt_history", JSON()))


def downgrade() -> None:
    bind = op.get_bind()
    existing = {item["name"] for item in inspect(bind).get_columns("analysis_runs")}
    for name in (
        "attempt_history",
        "failed_workspace_uri",
        "attempt_workspace_uri",
        "phase_updated_at",
        "execution_phase",
    ):
        if name in existing:
            op.drop_column("analysis_runs", name)
