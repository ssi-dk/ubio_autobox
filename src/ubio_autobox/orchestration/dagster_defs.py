"""Shallow Dagster orchestration around the one-sample application service."""

import hashlib
import json
from importlib.resources import files
from uuid import UUID

import dagster as dg
from dagster_slurm import (
    BashLauncher,
    ComputeResource,
    SlurmQueueConfig,
    SlurmResource,
    SlurmRunConfig,
    SSHConnectionResource,
)
from dagster_slurm.config.environment import ExecutionMode

from ubio_autobox.config import AppSettings
from ubio_autobox.execution.factory import build_repository
from ubio_autobox.ingest import FilesystemInputRegistry, StabilityCursor

SAMPLE_PARTITIONS = dg.DynamicPartitionsDefinition(name="samples")
ASSET_KEYS = (
    "validated_input",
    "bactopia_output",
    "normalized_results",
    "sample_quality",
    "atb_sample_export",
)


@dg.multi_asset(
    specs=[
        dg.AssetSpec(key=asset_key, partitions_def=SAMPLE_PARTITIONS)
        for asset_key in ASSET_KEYS
    ],
    can_subset=False,
)
def sample_analysis(  # type: ignore[no-untyped-def]
    context: dg.AssetExecutionContext,
    compute: ComputeResource,
    config: SlurmRunConfig,
):
    """Execute the whole sample graph through exactly one compute invocation."""

    sample_id = UUID(context.partition_key)
    settings = _settings()
    context.log.info(
        "Starting sample analysis for %s in Dagster run %s.",
        sample_id,
        context.run_id,
    )
    extra_env = {
        "UBIO_SAMPLE_ID": str(sample_id),
        "UBIO_DAGSTER_RUN_ID": context.run_id,
        "UBIO_DATABASE_URL": settings.database.url,
        "UBIO_INCOMING_ROOT": str(settings.paths.incoming_root),
        "UBIO_ARTIFACT_ROOT": str(settings.paths.artifact_root),
        "UBIO_CACHE_ROOT": str(settings.paths.cache_root),
        "UBIO_BACTOPIA_RUNNER": settings.bactopia.runner,
        "UBIO_BACTOPIA_PROFILE": settings.bactopia.profile,
        "UBIO_BACTOPIA_EXECUTABLE": settings.bactopia.executable,
        "UBIO_BACTOPIA_VERSION": settings.bactopia.version,
        "UBIO_BACTOPIA_MAX_CPUS": str(settings.bactopia.max_cpus),
        "UBIO_BACTOPIA_MAX_MEMORY": settings.bactopia.max_memory,
        "UBIO_BACTOPIA_DATABASE_VERSIONS": json.dumps(
            settings.bactopia.database_versions,
            sort_keys=True,
        ),
        "UBIO_BACTOPIA_EXTRA_ARGS": json.dumps(settings.bactopia.extra_args),
        "UBIO_BACTOPIA_CHECKM2_ARGS": json.dumps(settings.bactopia.checkm2_args),
        "UBIO_BACTOPIA_SYLPH_ARGS": json.dumps(settings.bactopia.sylph_args),
        "UBIO_ATB_SCHEMA_VERSION": settings.atb_schema_version,
        "UBIO_PIPELINE_CONFIG_FINGERPRINT": settings.pipeline_fingerprint(),
    }
    if settings.bactopia.image:
        extra_env["UBIO_BACTOPIA_IMAGE"] = settings.bactopia.image
    if settings.bactopia.container_digest:
        extra_env["UBIO_BACTOPIA_CONTAINER_DIGEST"] = settings.bactopia.container_digest
    if settings.bactopia.nextflow_version:
        extra_env["UBIO_NEXTFLOW_VERSION"] = settings.bactopia.nextflow_version
    try:
        invocation = compute.run(
            context=context,
            payload_path=str(files("ubio_autobox.execution") / "payload.py"),
            config=config,
            extra_env=extra_env,
            extra_slurm_opts=(
                _slurm_run_options(settings)
                if settings.execution.deployment == "slurm"
                else None
            ),
            poll_timeout=_wall_time_seconds(settings.slurm.wall_time) + 900,
        )
    except Exception:
        context.log.exception(
            "Sample analysis failed for %s in Dagster run %s.",
            sample_id,
            context.run_id,
        )
        raise
    context.log.info(
        "Completed sample analysis for %s in Dagster run %s.",
        sample_id,
        context.run_id,
    )
    return invocation.get_results()


SAMPLE_JOB = dg.define_asset_job(
    "process_sample",
    selection=list(ASSET_KEYS),
)


def _evaluate_incoming_samples(
    context: dg.SensorEvaluationContext, settings: AppSettings
) -> dg.SensorResult:
    """Register stable READY samples and launch idempotent per-sample runs."""

    repository = build_repository(settings)
    registry = FilesystemInputRegistry(
        settings.paths.incoming_root,
        repository,
        stability_observations=settings.sensor.stability_observations,
    )
    result = registry.discover_and_register(StabilityCursor.from_json(context.cursor))
    for error in result.errors:
        context.log.error(error)

    existing = set(context.instance.get_dynamic_partitions("samples"))
    partition_keys = [str(sample.sample_id) for sample in result.samples]
    new_keys = sorted(set(partition_keys) - existing)
    run_requests = [
        dg.RunRequest(
            run_key=_run_key(
                str(sample.sample_id),
                sample.input_fingerprint,
                settings.pipeline_fingerprint(),
            ),
            partition_key=str(sample.sample_id),
            tags={
                "ubio/sample_id": str(sample.sample_id),
                "ubio/input_fingerprint": sample.input_fingerprint,
                "ubio/trigger": "incoming_sample_sensor",
            },
        )
        for sample in result.samples
        if _is_launchable_sample(repository, sample.sample_id, settings)
    ]
    requests = [SAMPLE_PARTITIONS.build_add_request(new_keys)] if new_keys else []
    return dg.SensorResult(
        run_requests=run_requests,
        dynamic_partitions_requests=requests,
        cursor=result.cursor.to_json(),
    )


def build_incoming_sample_sensor(settings: AppSettings) -> dg.SensorDefinition:
    @dg.sensor(
        name="incoming_sample_sensor",
        job=SAMPLE_JOB,
        minimum_interval_seconds=settings.sensor.interval_seconds,
        default_status=dg.DefaultSensorStatus.RUNNING,
    )
    def incoming_sample_sensor(
        context: dg.SensorEvaluationContext,
    ) -> dg.SensorResult:
        return _evaluate_incoming_samples(context, settings)

    return incoming_sample_sensor


def _is_launchable_sample(
    repository: object, sample_id: UUID, settings: AppSettings
) -> bool:
    """Avoid re-queueing terminal or already active work on every poll."""

    status = repository.get_analysis_status(  # type: ignore[attr-defined]
        sample_id, settings.pipeline_fingerprint()
    )
    if status is None:
        return True
    return str(status.get("status")) == "validated"


def build_compute_resource(settings: AppSettings) -> ComputeResource:
    if settings.execution.deployment == "local":
        return ComputeResource(
            mode=ExecutionMode.LOCAL, default_launcher=BashLauncher()
        )

    slurm = settings.slurm
    ssh = SSHConnectionResource(
        host=str(slurm.host),
        port=slurm.port,
        user=str(slurm.user),
        key_path=str(slurm.key_path) if slurm.key_path else None,
        password=slurm.password,
    )
    resource = SlurmResource(
        ssh=ssh,
        queue=SlurmQueueConfig(
            partition=slurm.partition,
            time_limit=slurm.wall_time,
            cpus=slurm.cpus,
            mem=slurm.memory,
            qos=slurm.qos,
            account=slurm.account,
            num_nodes=1,
        ),
        remote_base=slurm.remote_base,
    )
    return ComputeResource(
        mode=ExecutionMode.SLURM,
        slurm=resource,
        default_launcher=BashLauncher(),
    )


def build_definitions(settings: AppSettings) -> dg.Definitions:
    global _ACTIVE_SETTINGS
    _ACTIVE_SETTINGS = settings
    return dg.Definitions(
        assets=[sample_analysis],
        jobs=[SAMPLE_JOB],
        sensors=[build_incoming_sample_sensor(settings)],
        resources={"compute": build_compute_resource(settings)},
    )


_ACTIVE_SETTINGS: AppSettings | None = None


def _settings() -> AppSettings:
    if _ACTIVE_SETTINGS is None:
        raise RuntimeError("Dagster definitions were not initialized")
    return _ACTIVE_SETTINGS


def _run_key(sample_id: str, input_fingerprint: str, config_fingerprint: str) -> str:
    value = f"{sample_id}:{input_fingerprint}:{config_fingerprint}".encode()
    return hashlib.sha256(value).hexdigest()


def _wall_time_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("Slurm wall_time must use HH:MM:SS")
    hours, minutes, seconds = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds


def _slurm_run_options(settings: AppSettings) -> dict[str, object]:
    slurm = settings.slurm
    options: dict[str, object] = {
        "nodes": 1,
        "cpus_per_task": slurm.cpus,
        "mem": slurm.memory,
        "time_limit": slurm.wall_time,
        "partition": slurm.partition,
        "qos": slurm.qos,
        "account": slurm.account,
    }
    aliases = {
        "--reservation": "reservation",
        "--nodes": "nodes",
        "--gpus-per-node": "gpus_per_node",
        "--mem-per-cpu": "mem_per_cpu",
    }
    for argument in slurm.extra_sbatch_args:
        flag, separator, value = argument.partition("=")
        if not separator or flag not in aliases or not value:
            raise ValueError(
                "extra_sbatch_args supports only --reservation=, --nodes=, "
                "--gpus-per-node=, and --mem-per-cpu="
            )
        key = aliases[flag]
        options[key] = int(value) if key in {"nodes", "gpus_per_node"} else value
    return {key: value for key, value in options.items() if value not in (None, "")}
