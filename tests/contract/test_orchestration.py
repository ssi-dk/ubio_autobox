from ubio_autobox.config import AppSettings
from ubio_autobox.orchestration.dagster_defs import (
    ASSET_KEYS,
    _run_key,
    build_definitions,
)


def test_definitions_load_with_five_logical_assets_one_compute_function() -> None:
    definitions = build_definitions(AppSettings())
    assert {
        spec.key.to_user_string() for spec in definitions.resolve_all_asset_specs()
    } == set(ASSET_KEYS)


def test_run_key_changes_with_scientific_identity() -> None:
    first = _run_key("sample", "input-a", "config")
    assert first == _run_key("sample", "input-a", "config")
    assert first != _run_key("sample", "input-b", "config")
