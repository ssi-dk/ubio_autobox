from __future__ import annotations

from pathlib import Path

import pytest

from ubio_autobox.config import AppSettings, load_settings


def test_default_paths_are_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = AppSettings()
    assert settings.paths.incoming_root.is_absolute()
    assert settings.database.url.startswith("duckdb:///")


def test_environment_overrides_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("bactopia:\n  runner: subprocess\n", encoding="utf-8")
    monkeypatch.setenv("UBIO_BACTOPIA_RUNNER", "fake")
    monkeypatch.setenv("UBIO_ATB_SCHEMA_VERSION", "2025-05")
    monkeypatch.setenv("UBIO_BACTOPIA_MAX_CPUS", "12")
    monkeypatch.setenv("UBIO_BACTOPIA_DATABASE_VERSIONS", '{"checkm2": "2026-01"}')
    monkeypatch.setenv("UBIO_BACTOPIA_CHECKM2_ARGS", '["--checkm2_db=/shared/checkm2"]')
    settings = load_settings(config)
    assert settings.bactopia.runner == "fake"
    assert settings.bactopia.max_cpus == 12
    assert settings.bactopia.database_versions == {"checkm2": "2026-01"}
    assert settings.bactopia.checkm2_args == ["--checkm2_db=/shared/checkm2"]
    assert settings.atb_schema_version == "2025-05"


def test_slurm_requires_absolute_shared_root() -> None:
    with pytest.raises(ValueError, match="absolute shared path"):
        AppSettings.model_validate(
            {
                "bactopia": {"profile": "singularity"},
                "execution": {
                    "deployment": "slurm",
                    "container_runtime": "apptainer",
                },
                "slurm": {
                    "host": "cluster",
                    "user": "service",
                    "password": "secret",
                    "remote_base": "relative/path",
                },
            }
        )


def test_container_runtime_and_bactopia_profile_must_agree() -> None:
    with pytest.raises(ValueError, match="requires bactopia.profile"):
        AppSettings.model_validate(
            {
                "execution": {"container_runtime": "apptainer"},
                "bactopia": {"profile": "docker"},
            }
        )
