"""Dagster Pipes payload: run all scientific work in one allocation."""

from __future__ import annotations

import os
from uuid import UUID

from dagster_pipes import open_dagster_pipes

from ubio_autobox.config import load_settings
from ubio_autobox.execution.factory import build_processor

ASSET_KEYS = (
    "validated_input",
    "bactopia_output",
    "normalized_results",
    "sample_quality",
    "atb_sample_export",
)


def main() -> None:
    sample_id = UUID(os.environ["UBIO_SAMPLE_ID"])
    settings = load_settings()
    processor = build_processor(settings)
    with open_dagster_pipes() as pipes:
        results = processor.process(
            sample_id,
            dagster_run_id=os.getenv("UBIO_DAGSTER_RUN_ID"),
            pipeline_config_fingerprint=os.getenv("UBIO_PIPELINE_CONFIG_FINGERPRINT"),
        )
        metadata: dict[str, int | str] = {
            "sample_id": str(results.sample_id),
            "analysis_id": str(results.analysis_id),
            "artifact_count": len(results.artifacts),
        }
        for asset_key in ASSET_KEYS:
            pipes.report_asset_materialization(
                asset_key=asset_key,
                metadata=metadata,
            )


if __name__ == "__main__":
    main()
