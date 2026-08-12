"""Parse structural Bactopia outputs into portable normalized records."""

from __future__ import annotations

import csv
import gzip
import hashlib
import re
from pathlib import Path
from typing import Any, TextIO

import yaml

from ubio_autobox.domain.errors import OutputParseError
from ubio_autobox.domain.models import (
    AnalysisRequest,
    NormalizedResultSet,
)

from .quality import QualityPolicy

_SAMPLE_ACCESSION = re.compile(r"^(?:SAM[END][A-Z]?\d+|[ESD]RS\d+)$")
_RUN_ACCESSION = re.compile(r"^[ESD]RR\d+$")


class BactopiaResultParser:
    """Own Bactopia file discovery, aliases, coercion, and quality fields."""

    def __init__(self, quality_policy: QualityPolicy | None = None) -> None:
        self._quality = quality_policy or QualityPolicy()

    def parse(
        self,
        analysis: AnalysisRequest,
        output_dir: Path,
        *,
        bactopia_version: str,
        nextflow_version: str | None,
        container_image: str | None,
        container_digest: str | None,
        database_versions: dict[str, str],
    ) -> NormalizedResultSet:
        sample = analysis.sample
        assembly_path = self._find_assembly(output_dir, sample.sample_key)
        assembly_stats = _assembly_statistics(assembly_path)
        checkm2 = self._parse_checkm2(
            self._find_merged(output_dir, "checkm2.tsv"), sample.sample_key
        )
        sylph = self._parse_sylph(
            self._find_merged(output_dir, "sylph.tsv"), sample.sample_key
        )
        quality = self._quality.assess(assembly_stats, checkm2, sylph)

        sample_accession = (
            sample.insdc_sample_accession
            if sample.insdc_sample_accession
            and _SAMPLE_ACCESSION.fullmatch(sample.insdc_sample_accession)
            else None
        )
        run_accession = (
            sample.source_record_id
            if sample.source_namespace in {"ena_run", "insdc_run"}
            and sample.source_record_id
            and _RUN_ACCESSION.fullmatch(sample.source_record_id)
            else None
        )
        for row in sylph:
            row["sample_accession"] = sample_accession
            row["run_accession"] = run_accession
        checkm2["sample_accession"] = sample_accession
        assembly_stats["sample_accession"] = sample_accession

        assembly_sha256 = _sha256(assembly_path)
        sequence_run = {
            "run_accession": run_accession,
            "sample_accession": sample_accession,
            "in_661k": None,
            "in_ena_20240625": None,
            "in_ena_20240801": None,
            "in_ena_20250506": None,
            "ena_202505_batch": None,
            "fastq_md5": None,
            "meta_pass_atb": None,
            "meta_pass_661k": None,
            "pass_value": None,
            "comments": (
                "Locally generated; ATB/661k metadata checks were not evaluated."
            ),
        }
        assembly = {
            "sample_accession": sample_accession,
            "run_accession": run_accession,
            "assembly_accession": None,
            "assembly_seqkit_sum": None,
            "asm_pipe_filter": quality.assembly_filter,
            "asm_fasta_on_osf": 0,
            "dataset": "ubio_autobox",
            "scientific_name": quality.scientific_name,
            "sylph_species_pre_202505": quality.sylph_species_pre_202505,
            "in_hq_pre_202505": quality.in_hq_pre_202505,
            "sylph_species": quality.scientific_name,
            "sylph_filter": quality.sylph_filter,
            "hq_filter": quality.hq_filter,
            "osf_tarball_filename": None,
            "osf_tarball_url": None,
            "aws_url": None,
            "comments": None,
            "assembly_uri": assembly_path.as_uri(),
            "assembly_sha256": assembly_sha256,
        }
        software: list[dict[str, Any]] = [
            {
                "name": "bactopia",
                "kind": "pipeline",
                "version": bactopia_version,
                "digest": container_digest,
                "metadata_json": (
                    {"image": container_image} if container_image else {}
                ),
            }
        ]
        if nextflow_version:
            software.append(
                {
                    "name": "nextflow",
                    "kind": "workflow_engine",
                    "version": nextflow_version,
                    "digest": None,
                    "metadata_json": {},
                }
            )
        software.extend(
            {
                "name": name,
                "kind": "reference_database",
                "version": version,
                "digest": None,
                "metadata_json": {},
            }
            for name, version in sorted(database_versions.items())
        )
        software.extend(_discover_execution_software(output_dir))
        return NormalizedResultSet(
            analysis_id=analysis.analysis_id,
            sample_id=sample.sample_id,
            sequence_run=sequence_run,
            assembly=assembly,
            assembly_stats=assembly_stats,
            sylph=sylph,
            checkm2=checkm2,
            software=tuple(software),
            attempt=analysis.attempt,
        )

    @staticmethod
    def _find_assembly(output_dir: Path, sample_key: str) -> Path:
        candidates = sorted(output_dir.rglob(f"{sample_key}.fna.gz"))
        if not candidates:
            candidates = sorted(output_dir.rglob(f"{sample_key}.fna"))
        preferred = [path for path in candidates if path.parent.name == "assembler"]
        selected = preferred or candidates
        if len(selected) != 1:
            raise OutputParseError(
                f"Expected one assembly for {sample_key!r}, found {len(selected)}"
            )
        if selected[0].stat().st_size == 0:
            raise OutputParseError("Assembly file is empty")
        return selected[0]

    @staticmethod
    def _find_merged(output_dir: Path, name: str) -> Path:
        candidates = sorted(output_dir.rglob(name))
        if not candidates:
            raise OutputParseError(f"Required Bactopia output {name} was not found")
        return max(candidates, key=lambda path: path.stat().st_mtime_ns)

    @staticmethod
    def _parse_checkm2(path: Path, sample_key: str) -> dict[str, Any]:
        rows = _rows_for_sample(path, sample_key)
        if len(rows) != 1:
            raise OutputParseError(
                f"Expected one CheckM2 row for {sample_key!r}, found {len(rows)}"
            )
        row = rows[0]
        return {
            "completeness_general": _float_any(
                row, "Completeness_General", "Completeness"
            ),
            "contamination": _float(row, "Contamination"),
            "completeness_specific": _float(row, "Completeness_Specific"),
            "completeness_model_used": _text(row, "Completeness_Model_Used"),
            "translation_table_used": _int(row, "Translation_Table_Used"),
            "coding_density": _float(row, "Coding_Density"),
            "contig_n50": _int(row, "Contig_N50"),
            "average_gene_length": _float(row, "Average_Gene_Length"),
            "genome_size": _int(row, "Genome_Size"),
            "gc_content": _float(row, "GC_Content"),
            "total_coding_sequences": _int(row, "Total_Coding_Sequences"),
            "additional_notes": _text(row, "Additional_Notes"),
        }

    @staticmethod
    def _parse_sylph(path: Path, sample_key: str) -> tuple[dict[str, Any], ...]:
        rows = _rows_for_sample(path, sample_key, allow_no_sample_column=True)
        return tuple(
            {
                "genome_file": _text(row, "Genome_file"),
                "taxonomic_abundance": _float(row, "Taxonomic_abundance"),
                "sequence_abundance": _float(row, "Sequence_abundance"),
                "adjusted_ani": _float(row, "Adjusted_ANI"),
                "eff_cov": _float(row, "Eff_cov"),
                "ani_5_95_percentile": _text_any(
                    row, "ANI_5_95_percentile", "ANI_5-95_percentile"
                ),
                "eff_lambda": _float(row, "Eff_lambda"),
                "lambda_5_95_percentile": _text_any(
                    row, "Lambda_5_95_percentile", "Lambda_5-95_percentile"
                ),
                "median_cov": _float(row, "Median_cov"),
                "mean_cov_geq1": _float(row, "Mean_cov_geq1"),
                "containment_ind": _text(row, "Containment_ind"),
                "naive_ani": _float(row, "Naive_ANI"),
                "contig_name": _text(row, "Contig_name"),
                "species": _text(row, "Species"),
            }
            for row in rows
        )


def _rows_for_sample(
    path: Path, sample_key: str, *, allow_no_sample_column: bool = False
) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = [dict(row) for row in reader]
    sample_column = next(
        (
            name
            for name in (
                "sample",
                "Sample",
                "Name",
                "Sample_file",
                "sample_accession",
            )
            if rows and name in rows[0]
        ),
        None,
    )
    if sample_column is None:
        if allow_no_sample_column:
            return rows
        raise OutputParseError(f"{path.name} has no sample identifier column")
    return [
        row for row in rows if _sample_value_matches(row.get(sample_column), sample_key)
    ]


def _sample_value_matches(value: str | None, sample_key: str) -> bool:
    if not value:
        return False
    stripped = value.strip()
    if stripped == sample_key:
        return True
    basename = Path(stripped).name
    return basename == sample_key or any(
        basename.startswith(f"{sample_key}{separator}") for separator in ("_", ".", "-")
    )


def _open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _assembly_statistics(path: Path) -> dict[str, Any]:
    lengths: list[int] = []
    n_count = 0
    gaps = 0
    current: list[str] = []
    with _open_text(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith(">"):
                if current:
                    sequence = "".join(current).upper()
                    lengths.append(len(sequence))
                    n_count += sequence.count("N")
                    gaps += len(re.findall(r"N+", sequence))
                    current = []
            elif line:
                current.append(line)
    if current:
        sequence = "".join(current).upper()
        lengths.append(len(sequence))
        n_count += sequence.count("N")
        gaps += len(re.findall(r"N+", sequence))
    if not lengths or any(length == 0 for length in lengths):
        raise OutputParseError("Assembly contains no non-empty contigs")

    total = sum(lengths)
    n50, n50n = _nx(lengths, 0.5)
    n70, n70n = _nx(lengths, 0.7)
    n90, n90n = _nx(lengths, 0.9)
    return {
        "total_length": total,
        "number": len(lengths),
        "mean_length": total / len(lengths),
        "longest": max(lengths),
        "shortest": min(lengths),
        "n_count": n_count,
        "gaps": gaps,
        "n50": n50,
        "n50n": n50n,
        "n70": n70,
        "n70n": n70n,
        "n90": n90,
        "n90n": n90n,
    }


def _nx(lengths: list[int], proportion: float) -> tuple[int, int]:
    target = sum(lengths) * proportion
    cumulative = 0
    for index, length in enumerate(sorted(lengths, reverse=True), start=1):
        cumulative += length
        if cumulative >= target:
            return length, index
    raise OutputParseError("Could not calculate assembly Nx statistic")


def _text(row: dict[str, str], key: str) -> str | None:
    value = row.get(key, "").strip()
    return value or None


def _text_any(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = _text(row, key)
        if value is not None:
            return value
    return None


def _float(row: dict[str, str], key: str) -> float | None:
    value = _text(row, key)
    try:
        return float(value) if value is not None else None
    except ValueError as error:
        raise OutputParseError(f"{key} is not numeric: {value!r}") from error


def _float_any(row: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        if _text(row, key) is not None:
            return _float(row, key)
    return None


def _int(row: dict[str, str], key: str) -> int | None:
    value = _float(row, key)
    return int(value) if value is not None else None


def _discover_execution_software(output_dir: Path) -> list[dict[str, Any]]:
    components: dict[tuple[str, str], dict[str, Any]] = {}

    for path in sorted(output_dir.rglob("versions.yml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        for name, version in _version_pairs(payload):
            key = ("software", name)
            component = components.setdefault(
                key,
                {
                    "name": name,
                    "kind": "software",
                    "version": version,
                    "digest": None,
                    "metadata_json": {"sources": []},
                },
            )
            if component["version"] != version:
                versions = {
                    item for item in str(component["version"]).split(",") if item
                }
                versions.add(version)
                component["version"] = ",".join(sorted(versions))
            component["metadata_json"]["sources"].append(
                str(path.relative_to(output_dir))
            )

    for path in sorted(output_dir.rglob("*-trace.txt")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        for row in rows:
            image = (row.get("container") or "").strip()
            if not image or image == "-":
                continue
            digest_match = re.search(r"@(?P<digest>sha256:[0-9a-fA-F]{64})$", image)
            digest = digest_match.group("digest").lower() if digest_match else None
            name = image[: digest_match.start()] if digest_match else image
            key = ("container", name)
            component = components.setdefault(
                key,
                {
                    "name": name,
                    "kind": "container",
                    "version": None,
                    "digest": digest,
                    "metadata_json": {"processes": [], "sources": []},
                },
            )
            process = (row.get("process") or row.get("name") or "").strip()
            if process:
                component["metadata_json"]["processes"].append(process)
            component["metadata_json"]["sources"].append(
                str(path.relative_to(output_dir))
            )

    for component in components.values():
        metadata = component["metadata_json"]
        for metadata_key in ("processes", "sources"):
            if metadata_key in metadata:
                metadata[metadata_key] = sorted(set(metadata[metadata_key]))
    return list(components.values())


def _version_pairs(value: object) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (str, int, float)):
                pairs.append((str(key), str(item)))
            else:
                pairs.extend(_version_pairs(item))
    elif isinstance(value, list):
        for item in value:
            pairs.extend(_version_pairs(item))
    return pairs


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
