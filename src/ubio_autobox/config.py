"""Validated application configuration with YAML and environment overrides."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _default_data_root() -> Path:
    configured = os.getenv("UBIO_DATA_ROOT")
    root = Path(configured) if configured else Path.cwd() / ".ubio"
    return root.expanduser().resolve()


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incoming_root: Path = Field(
        default_factory=lambda: _default_data_root() / "incoming"
    )
    artifact_root: Path = Field(
        default_factory=lambda: _default_data_root() / "artifacts"
    )
    cache_root: Path = Field(default_factory=lambda: _default_data_root() / "cache")

    @field_validator("*", mode="before")
    @classmethod
    def make_absolute(cls, value: object) -> Path:
        return Path(str(value)).expanduser().resolve()


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        default_factory=lambda: (
            f"duckdb:///{(_default_data_root() / 'state' / 'ubio.duckdb').as_posix()}"
        )
    )


class SensorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: int = Field(default=30, ge=5)
    stability_observations: int = Field(default=2, ge=1)


class BactopiaSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "4.0.0"
    executable: str = "bactopia"
    profile: Literal["docker", "singularity", "standard"] = "docker"
    runner: Literal["subprocess", "fake"] = "subprocess"
    max_cpus: int = Field(default=4, ge=1)
    max_memory: str = "16.GB"
    image: str | None = None
    container_digest: str | None = None
    nextflow_version: str | None = "26.04.6"
    database_versions: dict[str, str] = Field(default_factory=dict)
    extra_args: list[str] = Field(default_factory=list)
    checkm2_args: list[str] = Field(default_factory=list)
    sylph_args: list[str] = Field(default_factory=list)


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment: Literal["local", "slurm"] = "local"
    container_runtime: Literal["docker", "apptainer", "singularity", "native"] = (
        "docker"
    )


class SlurmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str | None = None
    port: int = Field(default=22, ge=1, le=65535)
    user: str | None = None
    key_path: Path | None = None
    password: str | None = None
    partition: str = ""
    account: str | None = None
    qos: str | None = None
    wall_time: str = "08:00:00"
    cpus: int = Field(default=8, ge=1)
    memory: str = "32G"
    remote_base: str = "/shared/ubio-autobox"
    extra_sbatch_args: list[str] = Field(default_factory=list)

    @field_validator("key_path", mode="before")
    @classmethod
    def expand_key_path(cls, value: object) -> Path | None:
        if value in (None, ""):
            return None
        return Path(str(value)).expanduser().resolve()


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: PathsSettings = Field(default_factory=PathsSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    sensor: SensorSettings = Field(default_factory=SensorSettings)
    bactopia: BactopiaSettings = Field(default_factory=BactopiaSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    slurm: SlurmSettings = Field(default_factory=SlurmSettings)
    atb_schema_version: str = "2025-05"

    @model_validator(mode="after")
    def validate_deployment(self) -> AppSettings:
        expected_profile = {
            "docker": "docker",
            "apptainer": "singularity",
            "singularity": "singularity",
            "native": "standard",
        }[self.execution.container_runtime]
        if self.bactopia.profile != expected_profile:
            raise ValueError(
                f"container_runtime={self.execution.container_runtime!r} requires "
                f"bactopia.profile={expected_profile!r}"
            )
        if self.execution.deployment == "slurm":
            if not self.slurm.host or not self.slurm.user:
                raise ValueError("Slurm deployment requires slurm.host and slurm.user")
            if bool(self.slurm.key_path) is bool(self.slurm.password):
                raise ValueError(
                    "Slurm deployment requires exactly one of key_path or password"
                )
            if not self.slurm.remote_base.startswith("/"):
                raise ValueError("slurm.remote_base must be an absolute shared path")
        return self

    def pipeline_fingerprint(self) -> str:
        payload = {
            "atb_schema_version": self.atb_schema_version,
            "bactopia": self.bactopia.model_dump(mode="json"),
            "execution": self.execution.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def ensure_runtime_directories(self) -> None:
        for path in (
            self.paths.incoming_root,
            self.paths.artifact_root,
            self.paths.cache_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

        if self.database.url.startswith("duckdb:///"):
            database_path = Path(self.database.url.removeprefix("duckdb:///"))
            database_path.parent.mkdir(parents=True, exist_ok=True)


def _deep_merge(target: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def load_settings(path: Path | str | None = None) -> AppSettings:
    """Load YAML configuration, then apply stable environment overrides."""

    configured_path = path or os.getenv("UBIO_CONFIG_FILE")
    data: dict[str, Any] = {}
    if configured_path:
        config_path = Path(configured_path).expanduser().resolve()
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("The application configuration must be a YAML mapping")
        data = loaded

    overrides: dict[str, Any] = {}
    if database_url := os.getenv("UBIO_DATABASE_URL"):
        overrides.setdefault("database", {})["url"] = database_url
    if incoming_root := os.getenv("UBIO_INCOMING_ROOT"):
        overrides.setdefault("paths", {})["incoming_root"] = incoming_root
    if artifact_root := os.getenv("UBIO_ARTIFACT_ROOT"):
        overrides.setdefault("paths", {})["artifact_root"] = artifact_root
    if cache_root := os.getenv("UBIO_CACHE_ROOT"):
        overrides.setdefault("paths", {})["cache_root"] = cache_root
    if deployment := os.getenv("UBIO_DEPLOYMENT"):
        overrides.setdefault("execution", {})["deployment"] = deployment
    if runner := os.getenv("UBIO_BACTOPIA_RUNNER"):
        overrides.setdefault("bactopia", {})["runner"] = runner
    if profile := os.getenv("UBIO_BACTOPIA_PROFILE"):
        overrides.setdefault("bactopia", {})["profile"] = profile
    if executable := os.getenv("UBIO_BACTOPIA_EXECUTABLE"):
        overrides.setdefault("bactopia", {})["executable"] = executable
    if version := os.getenv("UBIO_BACTOPIA_VERSION"):
        overrides.setdefault("bactopia", {})["version"] = version
    if max_cpus := os.getenv("UBIO_BACTOPIA_MAX_CPUS"):
        overrides.setdefault("bactopia", {})["max_cpus"] = int(max_cpus)
    if max_memory := os.getenv("UBIO_BACTOPIA_MAX_MEMORY"):
        overrides.setdefault("bactopia", {})["max_memory"] = max_memory
    if image := os.getenv("UBIO_BACTOPIA_IMAGE"):
        overrides.setdefault("bactopia", {})["image"] = image
    if digest := os.getenv("UBIO_BACTOPIA_CONTAINER_DIGEST"):
        overrides.setdefault("bactopia", {})["container_digest"] = digest
    if nextflow_version := os.getenv("UBIO_NEXTFLOW_VERSION"):
        overrides.setdefault("bactopia", {})["nextflow_version"] = nextflow_version
    for environment_name, field_name, expected_type in (
        ("UBIO_BACTOPIA_DATABASE_VERSIONS", "database_versions", dict),
        ("UBIO_BACTOPIA_EXTRA_ARGS", "extra_args", list),
        ("UBIO_BACTOPIA_CHECKM2_ARGS", "checkm2_args", list),
        ("UBIO_BACTOPIA_SYLPH_ARGS", "sylph_args", list),
    ):
        if raw_value := os.getenv(environment_name):
            parsed = json.loads(raw_value)
            if not isinstance(parsed, expected_type):
                raise ValueError(
                    f"{environment_name} must contain JSON {expected_type.__name__}"
                )
            overrides.setdefault("bactopia", {})[field_name] = parsed
    if atb_version := os.getenv("UBIO_ATB_SCHEMA_VERSION"):
        overrides["atb_schema_version"] = atb_version

    _deep_merge(data, overrides)
    return AppSettings.model_validate(data)
