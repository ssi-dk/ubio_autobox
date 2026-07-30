from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrades_empty_database(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "migration.sqlite"
    monkeypatch.setenv("UBIO_DATABASE_URL", f"sqlite+pysqlite:///{database}")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    assert (
        "samples"
        in inspect(create_engine(f"sqlite+pysqlite:///{database}")).get_table_names()
    )
