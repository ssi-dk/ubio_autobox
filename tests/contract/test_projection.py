from __future__ import annotations

from pathlib import Path

from tests.conftest import make_batch

from ubio_autobox.execution.factory import build_processor, build_repository
from ubio_autobox.ingest import FilesystemInputRegistry
from ubio_autobox.projection import AtbProjector


def test_tracer_bullet_persists_and_exports_all_tables(
    app_settings, tmp_path: Path
) -> None:
    make_batch(
        app_settings.paths.incoming_root,
        sample_accession="SAMEA123456",
        source_namespace="ena_run",
        source_record_id="ERR123456",
    )
    repository = build_repository(app_settings)
    registry = FilesystemInputRegistry(
        app_settings.paths.incoming_root, repository, stability_observations=2
    )
    first = registry.discover_and_register()
    registered = registry.discover_and_register(first.cursor).samples[0]

    result = build_processor(app_settings).process(registered.sample_id)
    bundle = repository.get_analysis_bundle(result.analysis_id)
    assert bundle["sequence_run"] is not None
    assert bundle["assembly_stats"] is not None
    assert bundle["checkm2"] is not None
    assert len(bundle["sylph"]) == 1
    containers = [
        component
        for component in bundle["software"]
        if component["kind"] == "container"
    ]
    assert containers[0]["name"].startswith("quay.io/biocontainers/shovill")
    assert containers[0]["digest"].startswith("sha256:")

    export_files = {
        path.name for path in app_settings.paths.artifact_root.rglob("*.parquet")
    }
    assert {
        "run.parquet",
        "assembly.parquet",
        "assembly_stats.parquet",
        "sylph.parquet",
        "checkm2.parquet",
        "sample_view.parquet",
    } <= export_files

    projector = AtbProjector()
    wide = projector.dataframe(repository)
    assert len(wide) == 1
    assert wide.iloc[0]["ubio_sample_id"] == str(registered.sample_id)
    assert wide.iloc[0]["sylph_hit_count"] == 1

    strict = projector.frames_from_results(result, mode="strict")
    assert len(strict["run"]) == 1
    assert "ubio_sample_id" not in strict["run"]


def test_strict_projection_never_substitutes_uuid(app_settings) -> None:
    make_batch(app_settings.paths.incoming_root)
    repository = build_repository(app_settings)
    registry = FilesystemInputRegistry(
        app_settings.paths.incoming_root, repository, stability_observations=1
    )
    sample = registry.discover_and_register().samples[0]
    result = build_processor(app_settings).process(sample.sample_id)
    strict = AtbProjector().frames_from_results(result, mode="strict")
    assert all(frame.empty for frame in strict.values())
