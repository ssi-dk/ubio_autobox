"""Operational CLI for initialization, discovery, processing, and export."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import typer

from ubio_autobox.config import load_settings
from ubio_autobox.domain.models import AnalysisStatus
from ubio_autobox.execution.factory import build_processor, build_repository
from ubio_autobox.ingest import FilesystemInputRegistry, StabilityCursor
from ubio_autobox.persistence import migrate_database
from ubio_autobox.projection import AtbProjector

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)

ANALYSIS_COMPLETE_EXIT = 0
ANALYSIS_TERMINAL_FAILURE_EXIT = 10
ANALYSIS_RETRYABLE_EXIT = 20


def _migrate(config: Path | None) -> None:
    settings = load_settings(config)
    settings.ensure_runtime_directories()
    migrate_database(settings.database.url)
    typer.echo("Result database migrated.")


@app.command("migrate")
def migrate(config: Path | None = None) -> None:
    """Upgrade the result database through the packaged Alembic revisions."""

    _migrate(config)


@app.command("init-db")
def init_database(config: Path | None = None) -> None:
    """Compatibility alias for ``migrate``."""

    _migrate(config)


@app.command()
def scan(
    config: Path | None = None,
    observations: int = typer.Option(
        1,
        min=1,
        help="Number of immediate evaluations; normal operation uses the sensor.",
    ),
) -> None:
    """Evaluate the incoming directory and register stable ready samples."""

    settings = load_settings(config)
    repository = build_repository(settings)
    registry = FilesystemInputRegistry(
        settings.paths.incoming_root,
        repository,
        stability_observations=settings.sensor.stability_observations,
    )
    cursor = StabilityCursor()
    registered: dict[str, str] = {}
    errors: list[str] = []
    for _ in range(observations):
        result = registry.discover_and_register(cursor)
        cursor = result.cursor
        errors.extend(result.errors)
        registered.update(
            {str(sample.sample_id): sample.sample_key for sample in result.samples}
        )
    typer.echo(
        json.dumps(
            {"registered": registered, "errors": errors},
            indent=2,
            sort_keys=True,
        )
    )


@app.command()
def process(sample_id: UUID, config: Path | None = None) -> None:
    """Process one already-registered sample without the Dagster UI."""

    settings = load_settings(config)
    result = build_processor(settings).process(sample_id)
    typer.echo(str(result.analysis_id))


@app.command()
def status(config: Path | None = None) -> None:
    """Show registered samples without exposing database credentials."""

    settings = load_settings(config)
    repository = build_repository(settings)
    typer.echo(json.dumps(repository.list_samples(), indent=2, default=str))


@app.command("analysis-status")
def analysis_status(
    sample_id: UUID,
    config: Path | None = None,
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON."),
) -> None:
    """Report current-pipeline analysis state using deployment-safe exit codes."""

    settings = load_settings(config)
    repository = build_repository(settings)
    result = repository.get_analysis_status(
        sample_id,
        settings.pipeline_fingerprint(),
    )
    if result is None:
        payload: dict[str, object] = {
            "sample_id": str(sample_id),
            "sample_key": None,
            "sample_status": "absent",
            "pipeline_config_fingerprint": settings.pipeline_fingerprint(),
            "analysis_id": None,
            "status": "absent",
            "attempt": None,
            "dagster_run_id": None,
            "error_summary": None,
            "started_at": None,
            "completed_at": None,
        }
    else:
        payload = result

    current_status = str(payload["status"])
    if json_output:
        typer.echo(json.dumps(payload, default=str, sort_keys=True))
    else:
        typer.echo(
            f"{payload['sample_id']} {current_status} "
            f"{payload.get('analysis_id') or '-'}"
        )

    if current_status == AnalysisStatus.SUCCEEDED.value:
        exit_code = ANALYSIS_COMPLETE_EXIT
    elif current_status in {
        AnalysisStatus.FAILED.value,
        AnalysisStatus.INVALID.value,
    }:
        exit_code = ANALYSIS_TERMINAL_FAILURE_EXIT
    else:
        exit_code = ANALYSIS_RETRYABLE_EXIT
    if exit_code:
        raise typer.Exit(exit_code)


@app.command("export-dataframe")
def export_dataframe(
    destination: Path,
    config: Path | None = None,
    strict: bool = False,
) -> None:
    """Write the one-row-per-analysis wide view as Parquet."""

    settings = load_settings(config)
    repository = build_repository(settings)
    frame = AtbProjector(settings.atb_schema_version).dataframe(
        repository,
        mode="strict" if strict else "extended",
    )
    resolved = destination.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(resolved, index=False)
    typer.echo(f"Wrote {len(frame)} rows to {resolved}")


@app.command("validate-config")
def validate_config(config: Path | None = None) -> None:
    """Validate settings and print only non-secret compatibility details."""

    settings = load_settings(config)
    typer.echo(
        json.dumps(
            {
                "deployment": settings.execution.deployment,
                "container_runtime": settings.execution.container_runtime,
                "bactopia_version": settings.bactopia.version,
                "atb_schema_version": settings.atb_schema_version,
                "pipeline_fingerprint": settings.pipeline_fingerprint(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
