from __future__ import annotations

import json

import pytest
from tests.conftest import make_batch, write_fastq

from ubio_autobox.domain.errors import (
    AnalysisAlreadyCompletedError,
    ExecutionFailedError,
    ImmutableInputError,
)
from ubio_autobox.domain.models import BactopiaRequest, ExecutionResult
from ubio_autobox.execution import FakeBactopiaRunner, LocalArtifactStore
from ubio_autobox.execution.factory import build_repository
from ubio_autobox.execution.processor import SampleProcessor
from ubio_autobox.ingest import FilesystemInputRegistry
from ubio_autobox.projection import AtbProjector, BactopiaResultParser


class FailingRunner:
    def run(self, request: BactopiaRequest) -> ExecutionResult:
        request.logs_dir.mkdir(parents=True, exist_ok=True)
        (request.logs_dir / "failure.log").write_text(
            "synthetic failure\n", encoding="utf-8"
        )
        raise ExecutionFailedError("synthetic runner failure")


def test_failed_attempt_is_retained_and_retry_gets_new_attempt(
    app_settings,
) -> None:
    make_batch(app_settings.paths.incoming_root)

    repository = build_repository(app_settings)
    registry = FilesystemInputRegistry(
        app_settings.paths.incoming_root, repository, stability_observations=1
    )
    sample = registry.discover_and_register().samples[0]
    artifacts = LocalArtifactStore(app_settings.paths.artifact_root)

    failed_processor = SampleProcessor(
        app_settings,
        repository,
        FailingRunner(),
        artifacts,
        BactopiaResultParser(),
        AtbProjector(),
    )
    with pytest.raises(ExecutionFailedError):
        failed_processor.process(sample.sample_id)
    failed_status = repository.get_analysis_status(
        sample.sample_id, app_settings.pipeline_fingerprint()
    )
    assert failed_status is not None
    assert failed_status["status"] == "failed"
    assert failed_status["execution_phase"] == "failed"
    assert str(failed_status["dagster_run_id"]).startswith("manual-")
    assert failed_status["failed_workspace_uri"]
    assert failed_status["logs_uri"]
    assert [event["phase"] for event in failed_status["phase_history"]] == [
        "queued",
        "validating_input",
        "preparing",
        "bactopia_core",
        "failed",
    ]
    assert all(
        event["completed_at"] is not None and event["duration_seconds"] >= 0
        for event in failed_status["phase_history"]
    )

    retry_processor = SampleProcessor(
        app_settings,
        repository,
        FakeBactopiaRunner(),
        artifacts,
        BactopiaResultParser(),
        AtbProjector(),
    )
    result = retry_processor.process(sample.sample_id)
    bundle = repository.get_analysis_bundle(result.analysis_id)
    assert bundle["analysis"]["attempt"] == 2
    assert list(
        app_settings.paths.artifact_root.rglob("failed/attempt-0001/logs/failure.log")
    )
    assert list(
        app_settings.paths.artifact_root.rglob(
            "published/attempt-0002/bactopia/sample-001/main/assembler/*.fna.gz"
        )
    )
    succeeded_status = repository.get_analysis_status(
        sample.sample_id, app_settings.pipeline_fingerprint()
    )
    assert succeeded_status is not None
    assert succeeded_status["status"] == "succeeded"
    assert succeeded_status["execution_phase"] == "succeeded"
    assert succeeded_status["attempt"] == 2
    assert succeeded_status["dagster_run_id"] != failed_status["dagster_run_id"]
    assert len(succeeded_status["attempt_history"]) == 1
    assert succeeded_status["attempt_history"][0]["status"] == "failed"
    phase_history = succeeded_status["phase_history"]
    assert [event["phase"] for event in phase_history] == [
        "queued",
        "validating_input",
        "preparing",
        "bactopia_core",
        "failed",
        "queued",
        "validating_input",
        "preparing",
        "bactopia_core",
        "checkm2",
        "sylph",
        "parsing_outputs",
        "exporting_results",
        "publishing_artifacts",
        "succeeded",
    ]
    assert [event["attempt"] for event in phase_history] == [1] * 5 + [2] * 10
    assert all(
        event["completed_at"] is not None and event["duration_seconds"] >= 0
        for event in phase_history
    )
    assert bundle["phase_history"] == phase_history

    manifest_path = next(
        app_settings.paths.artifact_root.rglob(
            "published/attempt-0002/attempt-manifest.json"
        )
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["attempt"] == 2
    assert manifest["status"] == "succeeded"
    assert manifest["phase"] == "succeeded"
    assert manifest["input_files"]
    assert manifest["artifacts"]


def test_new_analysis_flushes_before_initial_phase_event(app_settings) -> None:
    make_batch(app_settings.paths.incoming_root)
    repository = build_repository(app_settings)
    with repository.engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    sample = FilesystemInputRegistry(
        app_settings.paths.incoming_root, repository, stability_observations=1
    ).discover_and_register().samples[0]

    analysis = repository.ensure_analysis(
        sample.sample_id, app_settings.pipeline_fingerprint()
    )
    status = repository.get_analysis_status(
        sample.sample_id, app_settings.pipeline_fingerprint()
    )

    assert status is not None
    assert status["analysis_id"] == str(analysis.analysis_id)
    assert [event["phase"] for event in status["phase_history"]] == ["queued"]


def test_processing_rechecks_immutable_registered_reads(app_settings) -> None:
    batch = make_batch(app_settings.paths.incoming_root)
    repository = build_repository(app_settings)
    registry = FilesystemInputRegistry(
        app_settings.paths.incoming_root, repository, stability_observations=1
    )
    sample = registry.discover_and_register().samples[0]
    write_fastq(
        batch / "samples" / "sample-001" / "reads_R1.fastq.gz",
        "ACGTACGTACGT",
    )

    with pytest.raises(ImmutableInputError, match="changed after registration"):
        SampleProcessor(
            app_settings,
            repository,
            FakeBactopiaRunner(),
            LocalArtifactStore(app_settings.paths.artifact_root),
            BactopiaResultParser(),
            AtbProjector(),
        ).process(sample.sample_id)

    assert repository.list_samples()[0]["status"] == "invalid"


def test_successful_analysis_cannot_be_overwritten(app_settings) -> None:
    make_batch(app_settings.paths.incoming_root)
    repository = build_repository(app_settings)
    registry = FilesystemInputRegistry(
        app_settings.paths.incoming_root, repository, stability_observations=1
    )
    sample = registry.discover_and_register().samples[0]
    processor = SampleProcessor(
        app_settings,
        repository,
        FakeBactopiaRunner(),
        LocalArtifactStore(app_settings.paths.artifact_root),
        BactopiaResultParser(),
        AtbProjector(),
    )
    result = processor.process(sample.sample_id)

    with pytest.raises(AnalysisAlreadyCompletedError):
        processor.process(sample.sample_id)

    assert (
        repository.get_analysis_bundle(result.analysis_id)["analysis"]["status"]
        == "succeeded"
    )
