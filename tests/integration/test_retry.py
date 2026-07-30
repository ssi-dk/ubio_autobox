from __future__ import annotations

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
