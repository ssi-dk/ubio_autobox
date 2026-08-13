"""Composition root for the non-Dagster application services."""

from __future__ import annotations

from ubio_autobox.config import AppSettings
from ubio_autobox.domain.interfaces import BactopiaRunner
from ubio_autobox.persistence import SqlAlchemyResultRepository
from ubio_autobox.projection import AtbProjector, BactopiaResultParser

from .artifacts import LocalArtifactStore
from .processor import SampleProcessor
from .runner import FakeBactopiaRunner, SubprocessBactopiaRunner


def build_repository(settings: AppSettings) -> SqlAlchemyResultRepository:
    settings.ensure_runtime_directories()
    repository = SqlAlchemyResultRepository(settings.database.url)
    repository.initialize()
    return repository


def build_processor(settings: AppSettings) -> SampleProcessor:
    repository = build_repository(settings)
    runner: BactopiaRunner
    if settings.bactopia.runner == "fake":
        runner = FakeBactopiaRunner()
    else:
        runner = SubprocessBactopiaRunner()
    return SampleProcessor(
        settings=settings,
        repository=repository,
        runner=runner,
        artifacts=LocalArtifactStore(settings.paths.artifact_root),
        parser=BactopiaResultParser(),
        projector=AtbProjector(settings.atb_schema_version),
    )
