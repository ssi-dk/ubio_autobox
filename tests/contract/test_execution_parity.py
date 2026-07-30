from __future__ import annotations

import pandas as pd
from tests.conftest import make_batch

from ubio_autobox.config import (
    AppSettings,
    BactopiaSettings,
    ExecutionSettings,
    SlurmSettings,
)
from ubio_autobox.execution.factory import build_processor, build_repository
from ubio_autobox.ingest import FilesystemInputRegistry
from ubio_autobox.projection import AtbProjector


def test_local_and_slurm_transport_project_the_same_fixture(app_settings) -> None:
    make_batch(
        app_settings.paths.incoming_root,
        sample_accession="SAMEA123456",
        source_namespace="ena_run",
        source_record_id="ERR123456",
    )
    repository = build_repository(app_settings)
    sample = (
        FilesystemInputRegistry(
            app_settings.paths.incoming_root, repository, stability_observations=1
        )
        .discover_and_register()
        .samples[0]
    )
    local_result = build_processor(app_settings).process(sample.sample_id)

    synthetic_key = app_settings.paths.cache_root.parent / "synthetic-slurm-key"
    synthetic_key.write_text("not-a-real-key\n", encoding="utf-8")
    slurm_settings = AppSettings(
        paths=app_settings.paths,
        database=app_settings.database,
        bactopia=BactopiaSettings(runner="fake", profile="singularity"),
        execution=ExecutionSettings(deployment="slurm", container_runtime="apptainer"),
        slurm=SlurmSettings(
            host="cluster.example",
            user="service",
            key_path=synthetic_key,
        ),
    )
    slurm_result = build_processor(slurm_settings).process(sample.sample_id)
    projector = AtbProjector()
    local_frames = projector.frames_from_results(local_result, mode="strict")
    slurm_frames = projector.frames_from_results(slurm_result, mode="strict")
    for table_name in local_frames:
        pd.testing.assert_frame_equal(
            local_frames[table_name],
            slurm_frames[table_name],
        )
