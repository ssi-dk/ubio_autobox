"""Strict, extended, and wide AllTheBacteria projections."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pandas as pd

from ubio_autobox.domain.interfaces import ResultRepository
from ubio_autobox.domain.models import NormalizedResultSet, RegisteredSample

from .schema import AtbSchema, load_atb_schema

ProjectionMode = Literal["strict", "extended"]
_SAMPLE_ACCESSION = re.compile(r"^(?:SAM[END][A-Z]?\d+|[ESD]RS\d+)$")
_RUN_ACCESSION = re.compile(r"^[ESD]RR\d+$")


@dataclass(frozen=True, slots=True)
class ExportResult:
    export_id: UUID
    root: Path
    files: tuple[Path, ...]
    sample_view: pd.DataFrame


class AtbProjector:
    """Project one normalized model into all five ATB tables and a wide view."""

    def __init__(self, schema_version: str = "2025-05") -> None:
        self.schema: AtbSchema = load_atb_schema(schema_version)

    def frames_from_results(
        self,
        results: NormalizedResultSet,
        *,
        mode: ProjectionMode = "extended",
    ) -> dict[str, pd.DataFrame]:
        rows = _atb_rows(results)
        return self._frames(
            rows,
            results.sample_id,
            results.analysis_id,
            mode=mode,
        )

    def dataframe(
        self,
        repository: ResultRepository,
        analysis_ids: list[UUID] | None = None,
        *,
        mode: ProjectionMode = "extended",
    ) -> pd.DataFrame:
        ids = analysis_ids or repository.list_successful_analysis_ids()
        views: list[pd.DataFrame] = []
        for analysis_id in ids:
            bundle = repository.get_analysis_bundle(analysis_id)
            rows = _rows_from_bundle(bundle)
            sample_id = UUID(str(_mapping(bundle["analysis"])["sample_id"]))
            frames = self._frames(rows, sample_id, analysis_id, mode=mode)
            if mode == "strict" and all(frame.empty for frame in frames.values()):
                continue
            views.append(self.wide_view(frames))
        if not views:
            return pd.DataFrame()
        return pd.concat(views, ignore_index=True)

    def export_results(
        self,
        results: NormalizedResultSet,
        sample: RegisteredSample,
        export_parent: Path,
        *,
        mode: ProjectionMode = "extended",
        include_tsv: bool = False,
        include_sample_view_tsv: bool = False,
    ) -> ExportResult:
        export_id = uuid4()
        root = export_parent / str(export_id)
        root.mkdir(parents=True, exist_ok=False)
        frames = self.frames_from_results(results, mode=mode)
        sample_view = self.wide_view(frames)
        files: list[Path] = []
        for table_name, frame in frames.items():
            path = root / f"{table_name}.parquet"
            frame.to_parquet(path, index=False)
            files.append(path)
            if include_tsv:
                tsv_path = root / f"{table_name}.tsv"
                frame.to_csv(tsv_path, sep="\t", index=False)
                files.append(tsv_path)
        view_path = root / "sample_view.parquet"
        sample_view.to_parquet(view_path, index=False)
        files.append(view_path)
        if include_sample_view_tsv:
            sample_tsv_path = root / "sample_view.tsv"
            _without_accession_columns(sample_view).to_csv(
                sample_tsv_path,
                sep="\t",
                index=False,
                na_rep="",
            )
            files.append(sample_tsv_path)

        manifest_path = root / "manifest.json"
        manifest = {
            "export_id": str(export_id),
            "schema": f"allthebacteria-{self.schema.version}",
            "schema_source": self.schema.source,
            "mode": mode,
            "sample_id": str(sample.sample_id),
            "analysis_id": str(results.analysis_id),
            "files": {
                path.name: {
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in files
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        files.append(manifest_path)
        return ExportResult(
            export_id=export_id,
            root=root,
            files=tuple(files),
            sample_view=sample_view,
        )

    def wide_view(self, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        identity: dict[str, object] = {}
        for frame in frames.values():
            if not frame.empty and "ubio_sample_id" in frame:
                identity = {
                    "ubio_sample_id": frame.iloc[0]["ubio_sample_id"],
                    "ubio_analysis_id": frame.iloc[0]["ubio_analysis_id"],
                    "atb_schema_version": frame.iloc[0]["atb_schema_version"],
                }
                break

        row: dict[str, object] = dict(identity)
        for table_name in ("run", "assembly", "assembly_stats", "checkm2"):
            frame = frames[table_name]
            if frame.empty:
                for column in self.schema.tables[table_name].columns:
                    row[f"{table_name}__{column}"] = None
                continue
            for column in self.schema.tables[table_name].columns:
                row[f"{table_name}__{column}"] = frame.iloc[0][column]

        sylph = frames["sylph"]
        row["sylph_hit_count"] = len(sylph)
        if sylph.empty:
            for column in self.schema.tables["sylph"].columns:
                row[f"sylph__{column}"] = None
        else:
            abundance = pd.to_numeric(sylph["Taxonomic_abundance"], errors="coerce")
            top = sylph.loc[abundance.fillna(float("-inf")).idxmax()]
            for column in self.schema.tables["sylph"].columns:
                row[f"sylph__{column}"] = top[column]
        return pd.DataFrame([row])

    def _frames(
        self,
        rows: dict[str, list[dict[str, object]]],
        sample_id: UUID,
        analysis_id: UUID,
        *,
        mode: ProjectionMode,
    ) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for name, contract in self.schema.tables.items():
            frame = contract.frame(rows[name])
            if mode == "strict":
                frame = _strict_rows(name, frame)
            else:
                frame["ubio_sample_id"] = str(sample_id)
                frame["ubio_analysis_id"] = str(analysis_id)
                frame["atb_schema_version"] = self.schema.version
            frames[name] = frame
        return frames


def _atb_rows(
    results: NormalizedResultSet,
) -> dict[str, list[dict[str, object]]]:
    run = _rename(results.sequence_run, {"pass_value": "pass"})
    assembly = {
        key: value
        for key, value in results.assembly.items()
        if key not in {"assembly_uri", "assembly_sha256"}
    }
    stats = _rename(
        results.assembly_stats,
        {
            "n_count": "N_count",
            "gaps": "Gaps",
            "n50": "N50",
            "n50n": "N50n",
            "n70": "N70",
            "n70n": "N70n",
            "n90": "N90",
            "n90n": "N90n",
        },
    )
    sylph = [
        _rename(
            row,
            {
                "genome_file": "Genome_file",
                "taxonomic_abundance": "Taxonomic_abundance",
                "sequence_abundance": "Sequence_abundance",
                "adjusted_ani": "Adjusted_ANI",
                "eff_cov": "Eff_cov",
                "ani_5_95_percentile": "ANI_5_95_percentile",
                "eff_lambda": "Eff_lambda",
                "lambda_5_95_percentile": "Lambda_5_95_percentile",
                "median_cov": "Median_cov",
                "mean_cov_geq1": "Mean_cov_geq1",
                "containment_ind": "Containment_ind",
                "naive_ani": "Naive_ANI",
                "contig_name": "Contig_name",
                "species": "Species",
            },
        )
        for row in results.sylph
    ]
    checkm2 = _rename(
        results.checkm2,
        {
            "completeness_general": "Completeness_General",
            "contamination": "Contamination",
            "completeness_specific": "Completeness_Specific",
            "completeness_model_used": "Completeness_Model_Used",
            "translation_table_used": "Translation_Table_Used",
            "coding_density": "Coding_Density",
            "contig_n50": "Contig_N50",
            "average_gene_length": "Average_Gene_Length",
            "genome_size": "Genome_Size",
            "gc_content": "GC_Content",
            "total_coding_sequences": "Total_Coding_Sequences",
            "additional_notes": "Additional_Notes",
        },
    )
    return {
        "run": [run],
        "assembly": [assembly],
        "assembly_stats": [stats],
        "sylph": sylph,
        "checkm2": [checkm2],
    }


def _rows_from_bundle(
    bundle: dict[str, object],
) -> dict[str, list[dict[str, object]]]:
    def one(name: str) -> list[dict[str, object]]:
        value = bundle.get(name)
        return [_mapping(value)] if value is not None else []

    return {
        "run": one("sequence_run"),
        "assembly": one("assembly"),
        "assembly_stats": one("assembly_stats"),
        "sylph": [_mapping(row) for row in _sequence(bundle.get("sylph"))],
        "checkm2": one("checkm2"),
    }


def _strict_rows(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    sample_valid = (
        frame["sample_accession"]
        .fillna("")
        .astype(str)
        .str.fullmatch(_SAMPLE_ACCESSION)
    )
    valid = sample_valid
    if name in {"run", "assembly", "sylph"}:
        valid &= (
            frame["run_accession"].fillna("").astype(str).str.fullmatch(_RUN_ACCESSION)
        )
    return frame.loc[valid].reset_index(drop=True)


def _without_accession_columns(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        column
        for column in frame.columns
        if not str(column).lower().endswith("accession")
    ]
    return frame.loc[:, columns]


def _rename(row: dict[str, object], names: dict[str, str]) -> dict[str, object]:
    return {names.get(key, key): value for key, value in row.items()}


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"Expected a result mapping, got {type(value).__name__}")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"Expected a result list, got {type(value).__name__}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
