"""SQLAlchemy implementation of the result repository interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from ubio_autobox.domain.errors import (
    AnalysisAlreadyCompletedError,
    AnalysisNotFoundError,
    ImmutableInputError,
)
from ubio_autobox.domain.models import (
    AnalysisRequest,
    AnalysisStatus,
    FileRole,
    NormalizedResultSet,
    RegisteredSample,
    ValidatedSample,
)

from .models import (
    AnalysisRunModel,
    ArtifactModel,
    AssemblyResultModel,
    AssemblyStatsResultModel,
    Base,
    Checkm2ResultModel,
    IngestBatchModel,
    InputFileModel,
    SampleIdentifierModel,
    SampleModel,
    SequenceRunResultModel,
    SoftwareComponentModel,
    SylphResultModel,
    utc_now,
)

ModelT = TypeVar("ModelT", bound=Base)


class SqlAlchemyResultRepository:
    """Canonical persistence adapter for samples and scientific results."""

    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url)
        self._sessions = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def register_sample(self, sample: ValidatedSample) -> RegisteredSample:
        with self._sessions() as session:
            batch = session.scalar(
                select(IngestBatchModel).where(
                    IngestBatchModel.batch_key == sample.batch_key
                )
            )
            if batch is None:
                batch = IngestBatchModel(
                    batch_id=str(uuid4()),
                    batch_key=sample.batch_key,
                    manifest_uri=sample.manifest_path.as_uri(),
                    manifest_sha256=sample.manifest_sha256,
                )
                session.add(batch)
                session.flush()
            elif batch.manifest_sha256 != sample.manifest_sha256:
                session.query(SampleModel).filter(
                    SampleModel.batch_id == batch.batch_id
                ).update({"status": AnalysisStatus.INVALID.value})
                session.commit()
                raise ImmutableInputError(
                    f"Manifest changed after batch {sample.batch_key!r} was registered"
                )

            existing = session.scalar(
                select(SampleModel).where(
                    SampleModel.batch_id == batch.batch_id,
                    SampleModel.sample_key == sample.sample_key,
                )
            )
            if existing is not None:
                if existing.input_fingerprint != sample.input_fingerprint:
                    existing.status = AnalysisStatus.INVALID.value
                    existing.updated_at = utc_now()
                    session.commit()
                    raise ImmutableInputError(
                        "Ready input changed for "
                        f"{sample.batch_key}/{sample.sample_key}"
                    )
                if existing.status == AnalysisStatus.INVALID.value:
                    raise ImmutableInputError(
                        f"{sample.batch_key}/{sample.sample_key} was invalidated "
                        "and must be submitted under a new identity"
                    )
                return self._registered_from_model(session, existing)

            model = SampleModel(
                sample_id=str(uuid4()),
                batch_id=batch.batch_id,
                sample_key=sample.sample_key,
                insdc_sample_accession=sample.insdc_sample_accession,
                source_namespace=sample.source_namespace,
                source_record_id=sample.source_record_id,
                source_metadata=sample.source_metadata,
                manifest_row_sha256=sample.manifest_row_sha256,
                input_fingerprint=sample.input_fingerprint,
                status=AnalysisStatus.VALIDATED.value,
            )
            session.add(model)
            session.flush()

            for file_digest in sample.files:
                session.add(
                    InputFileModel(
                        input_file_id=str(uuid4()),
                        sample_id=model.sample_id,
                        role=file_digest.role.value,
                        uri=file_digest.path.as_uri(),
                        sha256=file_digest.sha256,
                        size_bytes=file_digest.size_bytes,
                    )
                )

            identifiers: set[tuple[str, str]] = set()
            if sample.insdc_sample_accession:
                identifiers.add(("insdc_sample", sample.insdc_sample_accession))
            if sample.source_namespace and sample.source_record_id:
                identifiers.add((sample.source_namespace, sample.source_record_id))
            for namespace, identifier in sorted(identifiers):
                session.add(
                    SampleIdentifierModel(
                        identifier_id=str(uuid4()),
                        sample_id=model.sample_id,
                        namespace=namespace,
                        identifier=identifier,
                    )
                )

            session.commit()
            return self._registered_from_model(session, model)

    def invalidate_sample(self, sample_id: UUID) -> None:
        with self._sessions.begin() as session:
            sample = session.get(SampleModel, str(sample_id))
            if sample is None:
                raise AnalysisNotFoundError(f"Sample {sample_id} does not exist")
            sample.status = AnalysisStatus.INVALID.value
            sample.updated_at = utc_now()

    def ensure_analysis(
        self,
        sample_id: UUID,
        pipeline_config_fingerprint: str,
        dagster_run_id: str | None = None,
    ) -> AnalysisRequest:
        with self._sessions() as session:
            sample = session.get(SampleModel, str(sample_id))
            if sample is None:
                raise AnalysisNotFoundError(f"Sample {sample_id} does not exist")
            if sample.status == AnalysisStatus.INVALID.value:
                raise ImmutableInputError(
                    f"Sample {sample_id} was invalidated and cannot be processed"
                )

            analysis = session.scalar(
                select(AnalysisRunModel).where(
                    AnalysisRunModel.sample_id == sample.sample_id,
                    AnalysisRunModel.input_fingerprint == sample.input_fingerprint,
                    AnalysisRunModel.pipeline_config_fingerprint
                    == pipeline_config_fingerprint,
                )
            )
            if analysis is None:
                analysis = AnalysisRunModel(
                    analysis_id=str(uuid4()),
                    sample_id=sample.sample_id,
                    attempt=1,
                    status=AnalysisStatus.QUEUED.value,
                    input_fingerprint=sample.input_fingerprint,
                    pipeline_config_fingerprint=pipeline_config_fingerprint,
                    dagster_run_id=dagster_run_id,
                )
                session.add(analysis)
            elif analysis.status == AnalysisStatus.FAILED.value:
                analysis.attempt += 1
                analysis.status = AnalysisStatus.QUEUED.value
                analysis.error_summary = None
                analysis.started_at = None
                analysis.completed_at = None
                analysis.dagster_run_id = dagster_run_id
            elif analysis.status == AnalysisStatus.SUCCEEDED.value:
                raise AnalysisAlreadyCompletedError(
                    f"Analysis {analysis.analysis_id} already succeeded for this "
                    "input and pipeline configuration"
                )
            elif dagster_run_id and not analysis.dagster_run_id:
                analysis.dagster_run_id = dagster_run_id

            session.commit()
            registered = self._registered_from_model(session, sample)
            return AnalysisRequest(
                analysis_id=UUID(analysis.analysis_id),
                sample=registered,
                attempt=analysis.attempt,
                pipeline_config_fingerprint=analysis.pipeline_config_fingerprint,
                dagster_run_id=analysis.dagster_run_id,
            )

    def mark_running(
        self, analysis_id: UUID, command_arguments: list[list[str]]
    ) -> None:
        with self._sessions.begin() as session:
            analysis = self._require_analysis(session, analysis_id)
            analysis.status = AnalysisStatus.RUNNING.value
            analysis.command_arguments = command_arguments
            analysis.started_at = utc_now()
            analysis.completed_at = None

    def complete_analysis(self, results: NormalizedResultSet) -> None:
        with self._sessions.begin() as session:
            analysis = self._require_analysis(session, results.analysis_id)

            self._replace_one(
                session,
                SequenceRunResultModel,
                results.analysis_id,
                results.sample_id,
                results.sequence_run,
            )
            self._replace_one(
                session,
                AssemblyResultModel,
                results.analysis_id,
                results.sample_id,
                results.assembly,
            )
            self._replace_one(
                session,
                AssemblyStatsResultModel,
                results.analysis_id,
                results.sample_id,
                results.assembly_stats,
            )
            self._replace_one(
                session,
                Checkm2ResultModel,
                results.analysis_id,
                results.sample_id,
                results.checkm2,
            )

            session.query(SylphResultModel).filter(
                SylphResultModel.analysis_id == str(results.analysis_id)
            ).delete()
            for row in results.sylph:
                session.add(
                    SylphResultModel(
                        sylph_result_id=str(uuid4()),
                        analysis_id=str(results.analysis_id),
                        sample_id=str(results.sample_id),
                        **row,
                    )
                )

            session.query(SoftwareComponentModel).filter(
                SoftwareComponentModel.analysis_id == str(results.analysis_id)
            ).delete()
            for component in results.software:
                session.add(
                    SoftwareComponentModel(
                        software_component_id=str(uuid4()),
                        analysis_id=str(results.analysis_id),
                        **component,
                    )
                )

            session.query(ArtifactModel).filter(
                ArtifactModel.analysis_id == str(results.analysis_id)
            ).delete()
            for artifact in results.artifacts:
                session.add(
                    ArtifactModel(
                        artifact_id=str(artifact.artifact_id),
                        analysis_id=str(results.analysis_id),
                        kind=artifact.kind,
                        uri=artifact.uri,
                        sha256=artifact.sha256,
                        size_bytes=artifact.size_bytes,
                        media_type=artifact.media_type,
                    )
                )

            analysis.status = AnalysisStatus.SUCCEEDED.value
            analysis.completed_at = utc_now()
            analysis.error_summary = None

    def fail_analysis(self, analysis_id: UUID, error: str) -> None:
        with self._sessions.begin() as session:
            analysis = self._require_analysis(session, analysis_id)
            analysis.status = AnalysisStatus.FAILED.value
            analysis.completed_at = utc_now()
            analysis.error_summary = error[-8000:]

    def get_registered_sample(self, sample_id: UUID) -> RegisteredSample:
        with self._sessions() as session:
            sample = session.get(SampleModel, str(sample_id))
            if sample is None:
                raise AnalysisNotFoundError(f"Sample {sample_id} does not exist")
            return self._registered_from_model(session, sample)

    def get_analysis_bundle(self, analysis_id: UUID) -> dict[str, object]:
        with self._sessions() as session:
            analysis = self._require_analysis(session, analysis_id)
            sample = session.get(SampleModel, analysis.sample_id)
            if sample is None:  # pragma: no cover - protected by the foreign key
                raise AnalysisNotFoundError(
                    f"Sample for analysis {analysis_id} does not exist"
                )

            return {
                "analysis": self._model_dict(analysis),
                "sample": self._model_dict(sample),
                "sequence_run": self._optional_model_dict(
                    session.get(SequenceRunResultModel, str(analysis_id))
                ),
                "assembly": self._optional_model_dict(
                    session.get(AssemblyResultModel, str(analysis_id))
                ),
                "assembly_stats": self._optional_model_dict(
                    session.get(AssemblyStatsResultModel, str(analysis_id))
                ),
                "checkm2": self._optional_model_dict(
                    session.get(Checkm2ResultModel, str(analysis_id))
                ),
                "sylph": sorted(
                    (
                        self._model_dict(row)
                        for row in session.scalars(
                            select(SylphResultModel).where(
                                SylphResultModel.analysis_id == str(analysis_id)
                            )
                        )
                    ),
                    key=_sylph_abundance_key,
                    reverse=True,
                ),
                "software": [
                    self._model_dict(row)
                    for row in session.scalars(
                        select(SoftwareComponentModel).where(
                            SoftwareComponentModel.analysis_id == str(analysis_id)
                        )
                    )
                ],
                "artifacts": [
                    self._model_dict(row)
                    for row in session.scalars(
                        select(ArtifactModel).where(
                            ArtifactModel.analysis_id == str(analysis_id)
                        )
                    )
                ],
            }

    def list_samples(self) -> list[dict[str, object]]:
        with self._sessions() as session:
            rows = session.scalars(
                select(SampleModel).order_by(
                    SampleModel.created_at, SampleModel.sample_key
                )
            )
            return [self._model_dict(row) for row in rows]

    def list_successful_analysis_ids(self) -> list[UUID]:
        with self._sessions() as session:
            values = session.scalars(
                select(AnalysisRunModel.analysis_id).where(
                    AnalysisRunModel.status == AnalysisStatus.SUCCEEDED.value
                )
            )
            return [UUID(value) for value in values]

    def _registered_from_model(
        self, session: Session, sample: SampleModel
    ) -> RegisteredSample:
        files = {
            item.role: (
                self._path_from_file_uri(item.uri),
                item.sha256,
                item.size_bytes,
            )
            for item in session.scalars(
                select(InputFileModel).where(
                    InputFileModel.sample_id == sample.sample_id
                )
            )
        }
        if FileRole.R1.value not in files or FileRole.R2.value not in files:
            raise AnalysisNotFoundError(
                f"Sample {sample.sample_id} does not have a complete read pair"
            )
        batch = session.get(IngestBatchModel, sample.batch_id)
        if batch is None:  # pragma: no cover - protected by the foreign key
            raise AnalysisNotFoundError(
                f"Batch for sample {sample.sample_id} does not exist"
            )
        return RegisteredSample(
            batch_id=UUID(sample.batch_id),
            sample_id=UUID(sample.sample_id),
            batch_key=batch.batch_key,
            sample_key=sample.sample_key,
            input_fingerprint=sample.input_fingerprint,
            r1=files[FileRole.R1.value][0],
            r2=files[FileRole.R2.value][0],
            r1_sha256=files[FileRole.R1.value][1],
            r2_sha256=files[FileRole.R2.value][1],
            r1_size_bytes=files[FileRole.R1.value][2],
            r2_size_bytes=files[FileRole.R2.value][2],
            insdc_sample_accession=sample.insdc_sample_accession,
            source_namespace=sample.source_namespace,
            source_record_id=sample.source_record_id,
        )

    @staticmethod
    def _require_analysis(session: Session, analysis_id: UUID) -> AnalysisRunModel:
        analysis = session.get(AnalysisRunModel, str(analysis_id))
        if analysis is None:
            raise AnalysisNotFoundError(f"Analysis {analysis_id} does not exist")
        return analysis

    @staticmethod
    def _replace_one(
        session: Session,
        model_type: type[ModelT],
        analysis_id: UUID,
        sample_id: UUID,
        values: dict[str, Any],
    ) -> None:
        existing = session.get(model_type, str(analysis_id))
        if existing is not None:
            session.delete(existing)
            session.flush()
        session.add(
            model_type(
                analysis_id=str(analysis_id),
                sample_id=str(sample_id),
                **values,
            )
        )

    @staticmethod
    def _model_dict(model: Base) -> dict[str, object]:
        return {
            attribute.columns[0].name: getattr(model, attribute.key)
            for attribute in inspect(model).mapper.column_attrs
        }

    @staticmethod
    def _path_from_file_uri(uri: str) -> Path:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise AnalysisNotFoundError(
                f"Unsupported input URI scheme: {parsed.scheme}"
            )
        return Path(unquote(parsed.path))

    @classmethod
    def _optional_model_dict(cls, model: Base | None) -> dict[str, object] | None:
        return cls._model_dict(model) if model is not None else None


def _sylph_abundance_key(row: dict[str, object]) -> tuple[bool, float]:
    value = row.get("Taxonomic_abundance")
    if isinstance(value, (int, float)):
        return True, float(value)
    return False, 0.0
