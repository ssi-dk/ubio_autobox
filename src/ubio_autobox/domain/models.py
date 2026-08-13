"""Immutable values passed across the main module seams."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID


class AnalysisStatus(StrEnum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALID = "invalid"


class ExecutionPhase(StrEnum):
    """Observable checkpoints inside one Bactopia analysis attempt."""

    QUEUED = "queued"
    VALIDATING_INPUT = "validating_input"
    PREPARING = "preparing"
    BACTOPIA_CORE = "bactopia_core"
    CHECKM2 = "checkm2"
    SYLPH = "sylph"
    PARSING_OUTPUTS = "parsing_outputs"
    EXPORTING_RESULTS = "exporting_results"
    PUBLISHING_ARTIFACTS = "publishing_artifacts"
    PERSISTING_RESULTS = "persisting_results"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PhaseStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FileRole(StrEnum):
    R1 = "r1"
    R2 = "r2"


@dataclass(frozen=True, slots=True)
class FileDigest:
    role: FileRole
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ValidatedSample:
    batch_key: str
    sample_key: str
    manifest_path: Path
    manifest_sha256: str
    manifest_row_sha256: str
    input_fingerprint: str
    files: tuple[FileDigest, FileDigest]
    insdc_sample_accession: str | None = None
    source_namespace: str | None = None
    source_record_id: str | None = None
    source_metadata: dict[str, str] = field(default_factory=dict)

    @property
    def r1(self) -> FileDigest:
        return next(item for item in self.files if item.role is FileRole.R1)

    @property
    def r2(self) -> FileDigest:
        return next(item for item in self.files if item.role is FileRole.R2)


@dataclass(frozen=True, slots=True)
class RegisteredSample:
    batch_id: UUID
    sample_id: UUID
    batch_key: str
    sample_key: str
    input_fingerprint: str
    r1: Path
    r2: Path
    r1_sha256: str | None = None
    r2_sha256: str | None = None
    r1_size_bytes: int | None = None
    r2_size_bytes: int | None = None
    insdc_sample_accession: str | None = None
    source_namespace: str | None = None
    source_record_id: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    analysis_id: UUID
    sample: RegisteredSample
    attempt: int
    pipeline_config_fingerprint: str
    dagster_run_id: str | None = None
    resume_from_phase: ExecutionPhase | None = None
    resume_workspace_uri: str | None = None
    resume_checkpoint_uri: str | None = None
    resume_checkpoint_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class BactopiaRequest:
    analysis: AnalysisRequest
    samplesheet_path: Path
    output_dir: Path
    logs_dir: Path
    executable: str
    profile: str
    max_cpus: int
    max_memory: str
    extra_args: tuple[str, ...] = ()
    checkm2_args: tuple[str, ...] = ()
    sylph_args: tuple[str, ...] = ()
    core_max_cpus: int | None = None
    core_max_memory: str | None = None
    checkm2_max_cpus: int | None = None
    checkm2_max_memory: str | None = None
    sylph_max_cpus: int | None = None
    sylph_max_memory: str | None = None
    phase_callback: Callable[[str, str], None] | None = None
    phase_complete_callback: Callable[[str, str], None] | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: UUID
    analysis_id: UUID
    kind: str
    uri: str
    sha256: str
    size_bytes: int
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    analysis_id: UUID
    output_dir: Path
    commands: tuple[tuple[str, ...], ...]
    return_codes: tuple[int, ...]
    started_at_iso: str
    completed_at_iso: str


@dataclass(frozen=True, slots=True)
class NormalizedResultSet:
    analysis_id: UUID
    sample_id: UUID
    sequence_run: dict[str, Any]
    assembly: dict[str, Any]
    assembly_stats: dict[str, Any]
    sylph: tuple[dict[str, Any], ...]
    checkm2: dict[str, Any]
    software: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    attempt: int = 0
