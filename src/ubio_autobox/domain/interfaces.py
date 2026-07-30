"""Small interfaces at the execution, storage, and persistence seams."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from .models import (
    AnalysisRequest,
    ArtifactRef,
    BactopiaRequest,
    ExecutionResult,
    NormalizedResultSet,
    RegisteredSample,
    ValidatedSample,
)


class ResultRepository(Protocol):
    def initialize(self) -> None: ...

    def register_sample(self, sample: ValidatedSample) -> RegisteredSample: ...

    def invalidate_sample(self, sample_id: UUID) -> None: ...

    def ensure_analysis(
        self,
        sample_id: UUID,
        pipeline_config_fingerprint: str,
        dagster_run_id: str | None = None,
    ) -> AnalysisRequest: ...

    def mark_running(
        self, analysis_id: UUID, command_arguments: list[list[str]]
    ) -> None: ...

    def complete_analysis(self, results: NormalizedResultSet) -> None: ...

    def fail_analysis(self, analysis_id: UUID, error: str) -> None: ...

    def get_registered_sample(self, sample_id: UUID) -> RegisteredSample: ...

    def get_analysis_bundle(self, analysis_id: UUID) -> dict[str, object]: ...

    def list_successful_analysis_ids(self) -> list[UUID]: ...


class BactopiaRunner(Protocol):
    def run(self, request: BactopiaRequest) -> ExecutionResult: ...


class ArtifactStore(Protocol):
    def allocate_attempt(
        self, sample_id: UUID, analysis_id: UUID, attempt: int
    ) -> Path: ...

    def publish_tree(
        self, analysis_id: UUID, root: Path
    ) -> tuple[ArtifactRef, ...]: ...

    def retain_failure(self, root: Path) -> Path: ...
