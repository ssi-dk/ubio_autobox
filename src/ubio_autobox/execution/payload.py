"""Dagster Pipes payload: run all scientific work in one allocation."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID

from dagster_pipes import open_dagster_pipes

from ubio_autobox.config import load_settings
from ubio_autobox.execution.factory import build_processor, build_repository

ASSET_KEYS = (
    "validated_input",
    "bactopia_output",
    "normalized_results",
    "sample_quality",
    "atb_sample_export",
)

_SUMMARY_FIELDS = (
    ("Sample ID", "ubio_sample_id"),
    ("Analysis ID", "ubio_analysis_id"),
    ("ATB schema", "atb_schema_version"),
    ("Run pass", "run__pass"),
    ("Scientific name", "assembly__scientific_name"),
    ("Assembly length", "assembly_stats__total_length"),
    ("Assembly N50", "assembly_stats__N50"),
    ("CheckM2 completeness", "checkm2__Completeness_General"),
    ("CheckM2 contamination", "checkm2__Contamination"),
    ("Sylph species", "sylph__Species"),
    ("Sylph abundance", "sylph__Taxonomic_abundance"),
)


def main() -> None:
    sample_id = UUID(os.environ["UBIO_SAMPLE_ID"])
    settings = load_settings()
    processor = build_processor(settings)
    with open_dagster_pipes() as pipes:

        def report_progress(phase: str, message: str) -> None:
            pipes.log.info("ubio phase=%s: %s", phase, message)
            pipes.report_custom_message(
                {
                    "type": "ubio_analysis_progress",
                    "sample_id": str(sample_id),
                    "phase": phase,
                    "message": message,
                }
            )

        results = processor.process(
            sample_id,
            dagster_run_id=os.getenv("UBIO_DAGSTER_RUN_ID"),
            pipeline_config_fingerprint=os.getenv("UBIO_PIPELINE_CONFIG_FINGERPRINT"),
            progress_callback=report_progress,
        )
        status = build_repository(settings).get_analysis_status(
            sample_id, settings.pipeline_fingerprint()
        )
        metadata: dict[str, Any] = {
            "sample_id": str(results.sample_id),
            "analysis_id": str(results.analysis_id),
            "attempt": results.attempt,
            "execution_phase": "succeeded",
            "artifact_count": len(results.artifacts),
            "artifact_root_uri": (
                settings.paths.artifact_root
                / "samples"
                / str(results.sample_id)
                / "analyses"
                / str(results.analysis_id)
                / "published"
                / f"attempt-{results.attempt:04d}"
            )
            .resolve()
            .as_uri(),
        }
        if status:
            for key in ("attempt_workspace_uri", "logs_uri"):
                value = status.get(key)
                if isinstance(value, str):
                    metadata[key] = value

        sample_export_metadata = dict(metadata)
        sample_tsv_uri = next(
            (
                artifact.uri
                for artifact in results.artifacts
                if artifact.uri.endswith("/sample_view.tsv")
            ),
            None,
        )
        if sample_tsv_uri is not None:
            sample_export_metadata = dict(metadata)
            sample_export_metadata["atb_sample_tsv_uri"] = sample_tsv_uri
            try:
                table_metadata, markdown_metadata = _sample_tsv_metadata(
                    _path_from_file_uri(sample_tsv_uri)
                )
            except (OSError, UnicodeError, ValueError, csv.Error) as error:
                pipes.log.warning(
                    "Could not build Dagster preview metadata for %s: %s",
                    sample_tsv_uri,
                    error,
                )
            else:
                sample_export_metadata["atb_sample_preview"] = table_metadata
                sample_export_metadata["atb_sample_summary"] = markdown_metadata
        for asset_key in ASSET_KEYS:
            pipes.report_asset_materialization(
                asset_key=asset_key,
                metadata=(
                    sample_export_metadata
                    if asset_key == "atb_sample_export"
                    else metadata
                ),
            )


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected a file URI, got {uri!r}")
    return Path(unquote(parsed.path))


def _sample_tsv_metadata(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = [field for field in (reader.fieldnames or []) if field]
        rows = [
            {field: (row.get(field) or None) for field in fieldnames} for row in reader
        ]

    table = {
        "type": "table",
        "raw_value": {
            "records": rows,
            "schema": [{"name": field, "type": "string"} for field in fieldnames],
        },
    }
    row = rows[0] if rows else {}
    markdown_rows = [
        f"| {label} | {_markdown_value(row.get(field))} |"
        for label, field in _SUMMARY_FIELDS
    ]
    markdown = {
        "type": "md",
        "raw_value": "\n".join(
            [
                "| Field | Value |",
                "| --- | --- |",
                *markdown_rows,
            ]
        ),
    }
    return table, markdown


def _markdown_value(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|")


if __name__ == "__main__":
    main()
