"""Dagster code-location entry point."""

from ubio_autobox.config import load_settings
from ubio_autobox.orchestration import build_definitions

defs = build_definitions(load_settings())
