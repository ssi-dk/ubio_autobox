from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import yaml
from tests.conftest import make_batch
from typer.testing import CliRunner

from ubio_autobox.cli import (
    ANALYSIS_COMPLETE_EXIT,
    ANALYSIS_RETRYABLE_EXIT,
    ANALYSIS_TERMINAL_FAILURE_EXIT,
    app,
)
from ubio_autobox.config import load_settings
from ubio_autobox.execution.factory import build_processor, build_repository
from ubio_autobox.ingest import FilesystemInputRegistry


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "incoming_root": str(tmp_path / "incoming"),
                    "artifact_root": str(tmp_path / "artifacts"),
                    "cache_root": str(tmp_path / "cache"),
                },
                "database": {
                    "url": f"sqlite+pysqlite:///{tmp_path / 'results.sqlite'}"
                },
                "bactopia": {
                    "runner": "fake",
                    "profile": "docker",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config


def _analysis_status(runner: CliRunner, sample_id: object, config: Path):
    result = runner.invoke(
        app,
        [
            "analysis-status",
            str(sample_id),
            "--config",
            str(config),
            "--json",
        ],
    )
    return result, json.loads(result.stdout)


def test_migrate_and_init_db_alias_are_idempotent(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    runner = CliRunner()

    first = runner.invoke(app, ["migrate", "--config", str(config)])
    second = runner.invoke(app, ["migrate", "--config", str(config)])
    alias = runner.invoke(app, ["init-db", "--config", str(config)])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert alias.exit_code == 0
    assert "Result database migrated." in alias.stdout
    assert build_repository(load_settings(config)).list_samples() == []


def test_analysis_status_json_and_exit_codes(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    settings = load_settings(config)
    repository = build_repository(settings)
    runner = CliRunner()

    absent_result, absent = _analysis_status(runner, uuid4(), config)
    assert absent_result.exit_code == ANALYSIS_RETRYABLE_EXIT
    assert absent["status"] == "absent"
    assert absent["analysis_id"] is None

    make_batch(settings.paths.incoming_root)
    sample = (
        FilesystemInputRegistry(
            settings.paths.incoming_root,
            repository,
            stability_observations=1,
        )
        .discover_and_register()
        .samples[0]
    )

    validated_result, validated = _analysis_status(runner, sample.sample_id, config)
    assert validated_result.exit_code == ANALYSIS_RETRYABLE_EXIT
    assert validated["status"] == "validated"

    analysis = repository.ensure_analysis(
        sample.sample_id,
        settings.pipeline_fingerprint(),
    )
    queued_result, queued = _analysis_status(runner, sample.sample_id, config)
    assert queued_result.exit_code == ANALYSIS_RETRYABLE_EXIT
    assert queued["status"] == "queued"
    assert queued["analysis_id"] == str(analysis.analysis_id)

    repository.mark_running(analysis.analysis_id, [["bactopia", "--redacted"]])
    running_result, running = _analysis_status(runner, sample.sample_id, config)
    assert running_result.exit_code == ANALYSIS_RETRYABLE_EXIT
    assert running["status"] == "running"

    repository.fail_analysis(analysis.analysis_id, "synthetic terminal failure")
    failed_result, failed = _analysis_status(runner, sample.sample_id, config)
    assert failed_result.exit_code == ANALYSIS_TERMINAL_FAILURE_EXIT
    assert failed["status"] == "failed"
    assert failed["error_summary"] == "synthetic terminal failure"

    completed = build_processor(settings).process(sample.sample_id)
    succeeded_result, succeeded = _analysis_status(runner, sample.sample_id, config)
    assert succeeded_result.exit_code == ANALYSIS_COMPLETE_EXIT
    assert succeeded["status"] == "succeeded"
    assert succeeded["analysis_id"] == str(completed.analysis_id)
