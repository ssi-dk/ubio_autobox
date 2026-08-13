"""Small interfaces at the execution, storage, and persistence seams."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from .models import (
    AnalysisRequest,
    ArtifactRef,
    BactopiaRequest,
    ExecutionPhase,
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
        self,
        analysis_id: UUID,
        command_arguments: list[list[str]],
        workspace_uri: str | None = None,
    ) -> None: ...

    def update_analysis_phase(
        self,
        analysis_id: UUID,
        phase: ExecutionPhase | str,
        workspace_uri: str | None = None,
    ) -> None: ...

    def complete_analysis_phase(
        self,
        analysis_id: UUID,
        phase: ExecutionPhase | str,
        checkpoint_uri: str | None = None,
        checkpoint_sha256: str | None = None,
    ) -> None: ...

    def complete_analysis(
        self, results: NormalizedResultSet, workspace_uri: str | None = None
    ) -> None: ...

    def fail_analysis(
        self,
        analysis_id: UUID,
        error: str,
        workspace_uri: str | None = None,
    ) -> None: ...

    def get_registered_sample(self, sample_id: UUID) -> RegisteredSample: ...

    def get_analysis_bundle(self, analysis_id: UUID) -> dict[str, object]: ...

    def get_analysis_status(
        self,
        sample_id: UUID,
        pipeline_config_fingerprint: str,
    ) -> dict[str, object] | None: ...

    def list_successful_analysis_ids(self) -> list[UUID]: ...


class BactopiaRunner(Protocol):
    def run(self, request: BactopiaRequest) -> ExecutionResult: ...


class ArtifactStore(Protocol):
    def allocate_attempt(
        self, sample_id: UUID, analysis_id: UUID, attempt: int
    ) -> Path: ...

    def seed_attempt_from_workspace(self, source: Path, target: Path) -> None: ...

    def publish_tree(
        self, analysis_id: UUID, root: Path
    ) -> tuple[ArtifactRef, ...]: ...

    def published_attempt_uri(self, analysis_id: UUID, attempt: int) -> str: ...

    def retain_failure(self, root: Path) -> Path: ...
