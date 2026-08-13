"""Safe Bactopia command construction and runner adapters."""

from __future__ import annotations

import csv
import gzip
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ubio_autobox.domain.errors import ExecutionFailedError
from ubio_autobox.domain.models import (
    BactopiaRequest,
    ExecutionResult,
    RegisteredSample,
)


def write_bactopia_samplesheet(sample: RegisteredSample, path: Path) -> None:
    """Write the Bactopia 4 one-sample FOFN without shell interpolation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "sample",
                "runtype",
                "genome_size",
                "species",
                "r1",
                "r2",
                "se",
                "ont",
                "assembly",
            ]
        )
        writer.writerow(
            [
                sample.sample_key,
                "paired-end",
                "",
                str(sample.source_metadata.get("species") or ""),
                str(sample.r1),
                str(sample.r2),
                "",
                "",
                "",
            ]
        )


class BactopiaCommandBuilder:
    """Resolve the three sequential Bactopia phases and their resources."""

    @staticmethod
    def build(request: BactopiaRequest) -> tuple[tuple[str, ...], ...]:
        _validate_extra_args(request.extra_args)
        _validate_extra_args(request.checkm2_args)
        _validate_extra_args(request.sylph_args)
        resume_index = _resume_start_index(request.analysis.resume_from_phase)
        core_common = _common(
            request,
            request.core_max_cpus,
            request.core_max_memory,
            resume=resume_index == 1,
        )
        checkm2_common = _common(
            request,
            request.checkm2_max_cpus,
            request.checkm2_max_memory,
            resume=resume_index == 2,
        )
        sylph_common = _common(
            request,
            request.sylph_max_cpus,
            request.sylph_max_memory,
            resume=resume_index == 3,
        )
        core = (
            request.executable,
            *core_common[:1],
            "--samples",
            str(request.samplesheet_path),
            "--outdir",
            str(request.output_dir),
            *core_common[1:],
            *request.extra_args,
        )
        checkm2 = (
            request.executable,
            *checkm2_common[:1],
            "--wf",
            "checkm2",
            "--bactopia",
            str(request.output_dir),
            *checkm2_common[1:],
            *request.checkm2_args,
        )
        sylph = (
            request.executable,
            *sylph_common[:1],
            "--wf",
            "sylph",
            "--bactopia",
            str(request.output_dir),
            *sylph_common[1:],
            *request.sylph_args,
        )
        return core, checkm2, sylph


class SubprocessBactopiaRunner:
    """Run Bactopia directly with argument arrays and retained logs."""

    def run(self, request: BactopiaRequest) -> ExecutionResult:
        commands = BactopiaCommandBuilder.build(request)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.logs_dir.mkdir(parents=True, exist_ok=True)
        started = _utc_iso()
        return_codes: list[int] = []

        resume_index = _resume_start_index(request.analysis.resume_from_phase)
        for index, command in enumerate(commands, start=1):
            if index < resume_index:
                return_codes.append(0)
                continue
            if request.phase_callback is not None:
                request.phase_callback(
                    _phase_for_command(index),
                    f"Running Bactopia command {index} of {len(commands)}.",
                )
            stdout_path = request.logs_dir / f"{index:02d}.stdout.log"
            stderr_path = request.logs_dir / f"{index:02d}.stderr.log"
            try:
                with (
                    stdout_path.open("wb") as stdout,
                    stderr_path.open("wb") as stderr,
                ):
                    result = subprocess.run(  # noqa: S603
                        command,
                        cwd=request.output_dir.parent,
                        check=False,
                        shell=False,
                        stdout=stdout,
                        stderr=stderr,
                    )
            except OSError as error:
                raise ExecutionFailedError(
                    f"Could not execute {command[0]!r}: {error}"
                ) from error
            return_codes.append(result.returncode)
            if result.returncode != 0:
                raise ExecutionFailedError(
                    f"Bactopia command {index} failed with exit code "
                    f"{result.returncode}; see {stderr_path}"
                )
            if request.phase_complete_callback is not None:
                request.phase_complete_callback(
                    _phase_for_command(index),
                    f"Completed Bactopia command {index} of {len(commands)}.",
                )

        return ExecutionResult(
            analysis_id=request.analysis.analysis_id,
            output_dir=request.output_dir,
            commands=commands,
            return_codes=tuple(return_codes),
            started_at_iso=started,
            completed_at_iso=_utc_iso(),
        )


class FakeBactopiaRunner:
    """Deterministic test runner that emits Bactopia-shaped scientific outputs."""

    _CONTIGS = (
        ("contig_1", "ACGT" * 800),
        ("contig_2", "GATTACA" * 300),
    )

    def run(self, request: BactopiaRequest) -> ExecutionResult:
        commands = BactopiaCommandBuilder.build(request)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        request.logs_dir.mkdir(parents=True, exist_ok=True)
        started = _utc_iso()
        sample_key = request.analysis.sample.sample_key

        assembly = (
            request.output_dir
            / sample_key
            / "main"
            / "assembler"
            / f"{sample_key}.fna.gz"
        )
        assembly.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(assembly, "wt", encoding="ascii") as handle:
            for name, sequence in self._CONTIGS:
                handle.write(f">{name}\n{sequence}\n")

        merged = request.output_dir / "bactopia-runs"
        _write_tsv(
            merged / "checkm2-fake" / "merged-results" / "checkm2.tsv",
            [
                {
                    "sample": sample_key,
                    "Completeness_General": "99.5",
                    "Contamination": "0.3",
                    "Completeness_Specific": "99.7",
                    "Completeness_Model_Used": "Specific",
                    "Translation_Table_Used": "11",
                    "Coding_Density": "0.88",
                    "Contig_N50": "3200",
                    "Average_Gene_Length": "900.2",
                    "Genome_Size": "5300",
                    "GC_Content": "50.0",
                    "Total_Coding_Sequences": "6",
                    "Additional_Notes": "",
                }
            ],
        )
        _write_tsv(
            merged / "sylph-fake" / "merged-results" / "sylph.tsv",
            [
                {
                    "sample": sample_key,
                    "Genome_file": "fake-reference",
                    "Taxonomic_abundance": "98.7",
                    "Sequence_abundance": "99.1",
                    "Adjusted_ANI": "99.1",
                    "Eff_cov": "30.2",
                    "ANI_5_95_percentile": "98.9-99.3",
                    "Eff_lambda": "30.2",
                    "Lambda_5_95_percentile": "29.0-31.4",
                    "Median_cov": "30",
                    "Mean_cov_geq1": "30.1",
                    "Containment_ind": "1",
                    "Naive_ANI": "99.0",
                    "Contig_name": "fake-reference",
                    "Species": "Escherichia coli",
                }
            ],
        )
        _write_tsv(
            request.output_dir / "bactopia-runs" / "bactopia-trace.txt",
            [
                {
                    "task_id": "1",
                    "process": "BACTOPIA:ASSEMBLER",
                    "container": (
                        "quay.io/biocontainers/shovill:1.1.0--pyhdfd78af_1"
                        "@sha256:"
                        "0123456789abcdef0123456789abcdef"
                        "0123456789abcdef0123456789abcdef"
                    ),
                }
            ],
        )
        resume_index = _resume_start_index(request.analysis.resume_from_phase)
        for index, command in enumerate(commands, start=1):
            if index < resume_index:
                continue
            if request.phase_callback is not None:
                request.phase_callback(
                    _phase_for_command(index),
                    f"Running deterministic test command {index} of {len(commands)}.",
                )
            (request.logs_dir / f"{index:02d}.stdout.log").write_text(
                f"fake execution: {command!r}\n", encoding="utf-8"
            )
            (request.logs_dir / f"{index:02d}.stderr.log").touch()
            if request.phase_complete_callback is not None:
                request.phase_complete_callback(
                    _phase_for_command(index),
                    f"Completed deterministic test command {index} of {len(commands)}.",
                )

        return ExecutionResult(
            analysis_id=request.analysis.analysis_id,
            output_dir=request.output_dir,
            commands=commands,
            return_codes=(0, 0, 0),
            started_at_iso=started,
            completed_at_iso=_utc_iso(),
        )


def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def copy_fixture_outputs(source: Path, destination: Path) -> None:
    """Copy an immutable captured Bactopia output tree into a test workspace."""

    shutil.copytree(source, destination, dirs_exist_ok=True)


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_extra_args(arguments: tuple[str, ...]) -> None:
    controlled = {
        "--samples",
        "--outdir",
        "--bactopia",
        "--wf",
        "-profile",
        "--max_cpus",
        "--max_memory",
        "--nfconfig",
        "--queue",
        "--cluster_opts",
        "--executor",
        "-resume",
    }
    for argument in arguments:
        flag = argument.partition("=")[0]
        if flag in controlled:
            raise ValueError(
                f"{flag} is controlled by ubio_autobox and cannot be overridden"
            )


def _phase_for_command(index: int) -> str:
    return {
        1: "bactopia_core",
        2: "checkm2",
        3: "sylph",
    }[index]


def _common(
    request: BactopiaRequest,
    max_cpus: int | None,
    max_memory: str | None,
    *,
    resume: bool,
) -> tuple[str, ...]:
    return (("-resume",) if resume else ()) + (
        "-profile",
        request.profile,
        "--max_cpus",
        str(max_cpus or request.max_cpus),
        "--max_memory",
        max_memory or request.max_memory,
    )


def _resume_start_index(phase: object) -> int:
    if phase == "bactopia_core":
        return 2
    if phase == "checkm2":
        return 3
    if phase == "sylph":
        return 4
    return 1
