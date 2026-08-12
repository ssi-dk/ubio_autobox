from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from unittest import mock

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from ubio_autobox.persistence import SqlAlchemyResultRepository


def test_initial_migration_upgrades_empty_database(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "migration.sqlite"
    monkeypatch.setenv("UBIO_DATABASE_URL", f"sqlite+pysqlite:///{database}")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    assert (
        "samples"
        in inspect(create_engine(f"sqlite+pysqlite:///{database}")).get_table_names()
    )


def test_phase_events_migrate_existing_observability_schema(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "legacy.sqlite"
    database_url = f"sqlite+pysqlite:///{database}"
    monkeypatch.setenv("UBIO_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "0002")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE analysis_phase_events"))

    command.upgrade(config, "head")
    assert "analysis_phase_events" in inspect(engine).get_table_names()


def test_migration_environment_is_packaged() -> None:
    migration_root = files("ubio_autobox.migrations")
    assert migration_root.joinpath("alembic.ini").is_file()
    assert migration_root.joinpath("script.py.mako").is_file()
    assert migration_root.joinpath("versions", "0001_normalized_results.py").is_file()
    assert migration_root.joinpath(
        "versions", "0002_analysis_observability.py"
    ).is_file()
    assert migration_root.joinpath(
        "versions", "0003_analysis_phase_events.py"
    ).is_file()


def test_repository_migration_preserves_exact_database_url(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'exact.sqlite'}?mode=rwc"
    repository = SqlAlchemyResultRepository(database_url)

    with mock.patch("ubio_autobox.persistence.repository.migrate_database") as migrate:
        repository.initialize()

    migrate.assert_called_once_with(database_url)
