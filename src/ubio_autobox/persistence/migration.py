"""App-owned database migration entry point."""

from __future__ import annotations

from importlib.resources import as_file, files

from alembic import command
from alembic.config import Config


def migrate_database(database_url: str) -> None:
    """Upgrade a configured scientific database to the packaged head revision."""

    migration_resources = files("ubio_autobox.migrations")
    with as_file(migration_resources) as migration_dir:
        config = Config(str(migration_dir / "alembic.ini"))
        config.set_main_option("script_location", str(migration_dir))
        config.attributes["database_url"] = database_url
        command.upgrade(config, "head")
