"""One-sample application service used by CLI, local Dagster, and Slurm."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from ubio_autobox.config import AppSettings
from ubio_autobox.domain.errors import ImmutableInputError
from ubio_autobox.domain.interfaces import (
    ArtifactStore,
    BactopiaRunner,
    ResultRepository,
)
from ubio_autobox.domain.models import (
    BactopiaRequest,
    NormalizedResultSet,
    RegisteredSample,
)
from ubio_autobox.projection import AtbProjector, BactopiaResultParser

from .runner import BactopiaCommandBuilder, write_bactopia_samplesheet


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
        samplesheet = workspace / "samples.tsv"
        output_dir = workspace / "bactopia"
        logs_dir = workspace / "logs"
        write_bactopia_samplesheet(analysis.sample, samplesheet)
        request = BactopiaRequest(
            analysis=analysis,
            samplesheet_path=samplesheet,
            output_dir=output_dir,
            logs_dir=logs_dir,
            executable=self._settings.bactopia.executable,
            profile=self._settings.bactopia.profile,
            max_cpus=self._settings.bactopia.max_cpus,
            max_memory=self._settings.bactopia.max_memory,
            extra_args=tuple(self._settings.bactopia.extra_args),
            checkm2_args=tuple(self._settings.bactopia.checkm2_args),
            sylph_args=tuple(self._settings.bactopia.sylph_args),
        )
        commands = BactopiaCommandBuilder.build(request)
        self._repository.mark_running(analysis.analysis_id, _redact_commands(commands))

        try:
            execution = self._runner.run(request)
            _verify_registered_inputs(analysis.sample)
            results = self._parser.parse(
                analysis,
                execution.output_dir,
                bactopia_version=self._settings.bactopia.version,
                nextflow_version=self._settings.bactopia.nextflow_version,
                container_image=self._settings.bactopia.image,
                container_digest=self._settings.bactopia.container_digest,
                database_versions=self._settings.bactopia.database_versions,
            )
            self._projector.export_results(
                results,
                analysis.sample,
                workspace / "exports",
                mode="extended",
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
            self._repository.complete_analysis(completed)
            return completed
        except Exception as error:
            if isinstance(error, ImmutableInputError):
                self._repository.invalidate_sample(sample_id)
            retained: Path | None = None
            if workspace.exists():
                retained = self._artifacts.retain_failure(workspace)
            summary = str(error)
            if retained is not None:
                summary = f"{summary}\nFailed workspace retained at {retained}"
            self._repository.fail_analysis(analysis.analysis_id, summary)
            raise


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
