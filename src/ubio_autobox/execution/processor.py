"""One-sample application service used by CLI, local Dagster, and Slurm."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

from ubio_autobox.config import AppSettings
from ubio_autobox.domain.errors import ImmutableInputError
from ubio_autobox.domain.interfaces import (
    ArtifactStore,
    BactopiaRunner,
    ResultRepository,
)
from ubio_autobox.domain.models import (
    AnalysisRequest,
    BactopiaRequest,
    ExecutionPhase,
    NormalizedResultSet,
    RegisteredSample,
)
from ubio_autobox.projection import AtbProjector, BactopiaResultParser

from .artifacts import AttemptManifest, inventory_files
from .runner import BactopiaCommandBuilder, write_bactopia_samplesheet

ProgressCallback = Callable[[str, str], None]


class SampleProcessor:
    """Own the complete transaction-like lifecycle of a sample analysis."""

    def __init__(
        self,
        settings: AppSettings,
        repository: ResultRepository,
        runner: BactopiaRunner,
        artifacts: ArtifactStore,
        parser: BactopiaResultParser,
        projector: AtbProjector,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._runner = runner
        self._artifacts = artifacts
        self._parser = parser
        self._projector = projector

    def process(
        self,
        sample_id: UUID,
        dagster_run_id: str | None = None,
        pipeline_config_fingerprint: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> NormalizedResultSet:
        registered = self._repository.get_registered_sample(sample_id)
        try:
            _verify_registered_inputs(registered)
        except ImmutableInputError:
            self._repository.invalidate_sample(sample_id)
            raise

        analysis = self._repository.ensure_analysis(
            sample_id,
            pipeline_config_fingerprint or self._settings.pipeline_fingerprint(),
            dagster_run_id,
        )
        workspace = self._artifacts.allocate_attempt(
            sample_id, analysis.analysis_id, analysis.attempt
        )
        workspace_uri = workspace.resolve().as_uri()
        manifest = AttemptManifest(
            workspace,
            {
                "schema_version": "ubio-autobox-attempt-1",
                "analysis_id": str(analysis.analysis_id),
                "sample_id": str(analysis.sample.sample_id),
                "batch_key": analysis.sample.batch_key,
                "sample_key": analysis.sample.sample_key,
                "attempt": analysis.attempt,
                "dagster_run_id": analysis.dagster_run_id,
                "input_fingerprint": analysis.sample.input_fingerprint,
                "pipeline_config_fingerprint": analysis.pipeline_config_fingerprint,
                "input_files": [
                    {
                        "role": role,
                        "uri": path.resolve().as_uri(),
                        "sha256": sha256,
                        "size_bytes": size_bytes,
                    }
                    for role, path, sha256, size_bytes in (
                        (
                            "r1",
                            analysis.sample.r1,
                            analysis.sample.r1_sha256,
                            analysis.sample.r1_size_bytes,
                        ),
                        (
                            "r2",
                            analysis.sample.r2,
                            analysis.sample.r2_sha256,
                            analysis.sample.r2_size_bytes,
                        ),
                    )
                ],
                "source_metadata": dict(analysis.sample.source_metadata),
                "status": "queued",
                "phase": ExecutionPhase.QUEUED.value,
                "resume_from_phase": (
                    analysis.resume_from_phase.value
                    if analysis.resume_from_phase is not None
                    else None
                ),
                "resume_workspace_uri": analysis.resume_workspace_uri,
                "resume_checkpoint_uri": analysis.resume_checkpoint_uri,
                "resume_checkpoint_sha256": analysis.resume_checkpoint_sha256,
            },
        )
        samplesheet = workspace / "samples.tsv"
        output_dir = workspace / "bactopia"
        logs_dir = workspace / "logs"
        checkpoints: dict[str, dict[str, object]] = {}
        try:
            if analysis.resume_workspace_uri is not None:
                _verify_resume_checkpoint(analysis)
                self._artifacts.seed_attempt_from_workspace(
                    _path_from_file_uri(analysis.resume_workspace_uri), workspace
                )
            self._set_phase(
                analysis.analysis_id,
                manifest,
                ExecutionPhase.VALIDATING_INPUT,
                workspace_uri,
                progress_callback,
                "Rechecking registered FASTQ checksums before execution.",
            )
            _verify_registered_inputs(analysis.sample)
            write_bactopia_samplesheet(analysis.sample, samplesheet)
            self._set_phase(
                analysis.analysis_id,
                manifest,
                ExecutionPhase.PREPARING,
                workspace_uri,
                progress_callback,
                "Prepared the one-sample Bactopia samplesheet.",
            )
            request = BactopiaRequest(
                analysis=analysis,
                samplesheet_path=samplesheet,
                output_dir=output_dir,
                logs_dir=logs_dir,
                executable=self._settings.bactopia.executable,
                profile=self._settings.bactopia.profile,
                max_cpus=self._settings.bactopia.max_cpus,
                max_memory=self._settings.bactopia.max_memory,
                core_max_cpus=self._settings.bactopia.core_max_cpus,
                core_max_memory=self._settings.bactopia.core_max_memory,
                checkm2_max_cpus=self._settings.bactopia.checkm2_max_cpus,
                checkm2_max_memory=self._settings.bactopia.checkm2_max_memory,
                sylph_max_cpus=self._settings.bactopia.sylph_max_cpus,
                sylph_max_memory=self._settings.bactopia.sylph_max_memory,
                extra_args=tuple(self._settings.bactopia.extra_args),
                checkm2_args=tuple(self._settings.bactopia.checkm2_args),
                sylph_args=tuple(self._settings.bactopia.sylph_args),
                phase_callback=lambda phase, message: self._set_phase(
                    analysis.analysis_id,
                    manifest,
                    phase,
                    workspace_uri,
                    progress_callback,
                    message,
                ),
                phase_complete_callback=lambda phase, message: self._complete_phase(
                    analysis.analysis_id,
                    analysis.attempt,
                    phase,
                    message,
                    workspace,
                    output_dir,
                    checkpoints,
                    manifest,
                ),
            )
            commands = BactopiaCommandBuilder.build(request)
            redacted_commands = _redact_commands(commands)
            manifest.update(commands=redacted_commands)
            self._repository.mark_running(
                analysis.analysis_id, redacted_commands, workspace_uri
            )
            first_phase = _first_bactopia_phase(analysis.resume_from_phase)
            if first_phase is not None:
                self._set_phase(
                    analysis.analysis_id,
                    manifest,
                    first_phase,
                    workspace_uri,
                    progress_callback,
                    f"Starting {first_phase.value} phase.",
                )
            execution = self._runner.run(request)
            _verify_registered_inputs(analysis.sample)
            self._set_phase(
                analysis.analysis_id,
                manifest,
                ExecutionPhase.PARSING_OUTPUTS,
                workspace_uri,
                progress_callback,
                "Parsing the required Bactopia, CheckM2, and Sylph outputs.",
            )
            results = self._parser.parse(
                analysis,
                execution.output_dir,
                bactopia_version=self._settings.bactopia.version,
                nextflow_version=self._settings.bactopia.nextflow_version,
                container_image=self._settings.bactopia.image,
                container_digest=self._settings.bactopia.container_digest,
                database_versions=self._settings.bactopia.database_versions,
            )
            self._set_phase(
                analysis.analysis_id,
                manifest,
                ExecutionPhase.EXPORTING_RESULTS,
                workspace_uri,
                progress_callback,
                "Writing structured ATB exports and their manifest.",
            )
            self._projector.export_results(
                results,
                analysis.sample,
                workspace / "exports",
                mode="extended",
                include_sample_view_tsv=True,
            )
            self._set_phase(
                analysis.analysis_id,
                manifest,
                ExecutionPhase.PUBLISHING_ARTIFACTS,
                workspace_uri,
                progress_callback,
                "Checksumming and atomically publishing the attempt artifacts.",
            )
            manifest.update(
                status="succeeded",
                phase=ExecutionPhase.SUCCEEDED.value,
                completed_at=execution.completed_at_iso,
                return_codes=list(execution.return_codes),
                checkpoints=checkpoints,
                artifacts=inventory_files(workspace, exclude={manifest.path}),
            )
            artifact_refs = self._artifacts.publish_tree(
                analysis.analysis_id, workspace
            )
            assembly_artifact = next(
                (
                    item
                    for item in artifact_refs
                    if item.kind == "assembly"
                    and Path(item.uri).name.startswith(analysis.sample.sample_key)
                ),
                None,
            )
            assembly = dict(results.assembly)
            if assembly_artifact is not None:
                assembly["assembly_uri"] = assembly_artifact.uri
                assembly["assembly_sha256"] = assembly_artifact.sha256
            completed = replace(
                results,
                assembly=assembly,
                artifacts=artifact_refs,
            )
            self._repository.complete_analysis(
                completed,
                self._artifacts.published_attempt_uri(
                    analysis.analysis_id, analysis.attempt
                ),
            )
            return completed
        except Exception as error:
            if isinstance(error, ImmutableInputError):
                self._repository.invalidate_sample(sample_id)
            retained: Path | None = None
            summary = str(error)
            if workspace.exists():
                manifest.update(
                    status="failed",
                    phase=ExecutionPhase.FAILED.value,
                    error_summary=summary[-8000:],
                )
                retained = self._artifacts.retain_failure(workspace)
            if retained is not None:
                summary = f"{summary}\nFailed workspace retained at {retained}"
            self._repository.fail_analysis(
                analysis.analysis_id,
                summary,
                retained.resolve().as_uri() if retained is not None else None,
            )
            raise

    def _complete_phase(
        self,
        analysis_id: UUID,
        attempt: int,
        phase: str,
        message: str,
        workspace: Path,
        output_dir: Path,
        checkpoints: dict[str, dict[str, object]],
        manifest: AttemptManifest,
    ) -> None:
        phase_value = phase.value if isinstance(phase, ExecutionPhase) else str(phase)
        if phase_value not in {
            ExecutionPhase.BACTOPIA_CORE.value,
            ExecutionPhase.CHECKM2.value,
            ExecutionPhase.SYLPH.value,
        }:
            return
        checkpoint_path = _write_phase_checkpoint(
            workspace, output_dir, analysis_id, attempt, phase_value
        )
        checkpoint_sha256 = _sha256_file(checkpoint_path)
        checkpoint = {
            "uri": checkpoint_path.resolve().as_uri(),
            "sha256": checkpoint_sha256,
            "phase": phase_value,
        }
        checkpoints[phase_value] = checkpoint
        checkpoint_uri = str(checkpoint["uri"])
        self._repository.complete_analysis_phase(
            analysis_id,
            phase_value,
            checkpoint_uri,
            checkpoint_sha256,
        )
        manifest.update(checkpoints=checkpoints, message=message)

    def _set_phase(
        self,
        analysis_id: UUID,
        manifest: AttemptManifest,
        phase: ExecutionPhase | str,
        workspace_uri: str,
        progress_callback: ProgressCallback | None,
        message: str,
    ) -> None:
        phase_value = phase.value if isinstance(phase, ExecutionPhase) else phase
        self._repository.update_analysis_phase(analysis_id, phase_value, workspace_uri)
        manifest.update(status="running", phase=phase_value, message=message)
        if progress_callback is not None:
            progress_callback(phase_value, message)


def _verify_registered_inputs(sample: RegisteredSample) -> None:
    expected = (
        (sample.r1, sample.r1_sha256, sample.r1_size_bytes, "r1"),
        (sample.r2, sample.r2_sha256, sample.r2_size_bytes, "r2"),
    )
    for path, expected_sha256, expected_size, role in expected:
        if expected_sha256 is None or expected_size is None:
            raise ImmutableInputError(f"Registered {role} provenance is incomplete")
        try:
            actual_size = path.stat().st_size
        except OSError as error:
            raise ImmutableInputError(
                f"Registered {role} is no longer readable: {path}"
            ) from error
        if actual_size != expected_size:
            raise ImmutableInputError(
                f"Registered {role} size changed after registration: {path}"
            )
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise ImmutableInputError(
                f"Registered {role} is no longer readable: {path}"
            ) from error
        if digest.hexdigest() != expected_sha256:
            raise ImmutableInputError(
                f"Registered {role} checksum changed after registration: {path}"
            )


def _write_phase_checkpoint(
    workspace: Path,
    output_dir: Path,
    analysis_id: UUID,
    attempt: int,
    phase: str,
) -> Path:
    if phase == ExecutionPhase.BACTOPIA_CORE.value:
        candidates = sorted(output_dir.rglob("*.fna.gz"))
        if not candidates:
            candidates = sorted(output_dir.rglob("*.fna"))
        preferred = [path for path in candidates if path.parent.name == "assembler"]
        required = preferred or candidates
    else:
        required = sorted(output_dir.rglob(f"{phase}.tsv"))
    if not required:
        raise ValueError(f"Cannot checkpoint {phase}: required output is missing")

    checkpoint_dir = workspace / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / f"{phase}.json"
    payload = {
        "schema_version": "ubio-autobox-phase-checkpoint-1",
        "analysis_id": str(analysis_id),
        "attempt": attempt,
        "phase": phase,
        "output_root": "bactopia",
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in required
        ],
    }
    checkpoint_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return checkpoint_path


def _first_bactopia_phase(
    completed_phase: ExecutionPhase | None,
) -> ExecutionPhase | None:
    return {
        None: ExecutionPhase.BACTOPIA_CORE,
        ExecutionPhase.BACTOPIA_CORE: ExecutionPhase.CHECKM2,
        ExecutionPhase.CHECKM2: ExecutionPhase.SYLPH,
        ExecutionPhase.SYLPH: None,
    }[completed_phase]


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected a file URI, got {uri!r}")
    return Path(unquote(parsed.path))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_resume_checkpoint(analysis: AnalysisRequest) -> None:
    checkpoint_uri = analysis.resume_checkpoint_uri
    checkpoint_sha256 = analysis.resume_checkpoint_sha256
    workspace_uri = analysis.resume_workspace_uri
    resume_phase = analysis.resume_from_phase
    if (
        not checkpoint_uri
        or not checkpoint_sha256
        or not workspace_uri
        or not resume_phase
    ):
        raise ValueError("Resume metadata is incomplete")
    checkpoint = _path_from_file_uri(checkpoint_uri).resolve(strict=True)
    workspace = _path_from_file_uri(workspace_uri).resolve(strict=True)
    if not checkpoint.is_relative_to(workspace):
        raise ValueError("Resume checkpoint escapes the retained workspace")
    if _sha256_file(checkpoint) != checkpoint_sha256:
        raise ValueError("Resume checkpoint checksum does not match the database")
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    if payload.get("phase") != resume_phase.value:
        raise ValueError("Resume checkpoint phase does not match the database")
    output_root = workspace / "bactopia"
    for item in payload.get("files", []):
        relative = Path(str(item["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Resume checkpoint output escapes Bactopia workspace")
        output = output_root / relative
        if not output.exists():
            raise ValueError(f"Resume checkpoint output is missing: {relative}")
        if output.stat().st_size != int(item["size_bytes"]):
            raise ValueError(f"Resume checkpoint size mismatch: {relative}")
        if _sha256_file(output) != item["sha256"]:
            raise ValueError(f"Resume checkpoint checksum mismatch: {relative}")


def _redact_commands(
    commands: tuple[tuple[str, ...], ...],
) -> list[list[str]]:
    sensitive = ("password", "passwd", "secret", "token", "api-key", "apikey")
    redacted: list[list[str]] = []
    for command in commands:
        output: list[str] = []
        hide_next = False
        for argument in command:
            if hide_next:
                output.append("<redacted>")
                hide_next = False
                continue
            lowered = argument.lower()
            if "=" in argument and any(word in lowered for word in sensitive):
                output.append(f"{argument.partition('=')[0]}=<redacted>")
                continue
            output.append(argument)
            if argument.startswith("-") and any(word in lowered for word in sensitive):
                hide_next = True
        redacted.append(output)
    return redacted
