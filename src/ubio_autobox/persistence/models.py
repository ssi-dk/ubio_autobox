"""Portable SQLAlchemy models for identity, provenance, and normalized results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class IngestBatchModel(Base):
    __tablename__ = "ingest_batches"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    manifest_uri: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    samples: Mapped[list[SampleModel]] = relationship(back_populates="batch")


class SampleModel(Base):
    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint("batch_id", "sample_key", name="uq_sample_batch_key"),
    )

    sample_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("ingest_batches.batch_id"), nullable=False, index=True
    )
    sample_key: Mapped[str] = mapped_column(String(255), nullable=False)
    insdc_sample_accession: Mapped[str | None] = mapped_column(String(64))
    source_namespace: Mapped[str | None] = mapped_column(String(255))
    source_record_id: Mapped[str | None] = mapped_column(String(255))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    manifest_row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    batch: Mapped[IngestBatchModel] = relationship(back_populates="samples")
    files: Mapped[list[InputFileModel]] = relationship(back_populates="sample")
    identifiers: Mapped[list[SampleIdentifierModel]] = relationship(
        back_populates="sample"
    )
    analyses: Mapped[list[AnalysisRunModel]] = relationship(back_populates="sample")


class SampleIdentifierModel(Base):
    __tablename__ = "sample_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "namespace", "identifier", name="uq_sample_identifier_namespace"
        ),
    )

    identifier_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False)

    sample: Mapped[SampleModel] = relationship(back_populates="identifiers")


class InputFileModel(Base):
    __tablename__ = "input_files"
    __table_args__ = (
        UniqueConstraint("sample_id", "role", name="uq_input_file_sample_role"),
    )

    input_file_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    sample: Mapped[SampleModel] = relationship(back_populates="files")


class AnalysisRunModel(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "sample_id",
            "input_fingerprint",
            "pipeline_config_fingerprint",
            name="uq_analysis_identity",
        ),
    )

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    dagster_run_id: Mapped[str | None] = mapped_column(String(255))
    command_arguments: Mapped[list[list[str]] | None] = mapped_column(JSON)
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    sample: Mapped[SampleModel] = relationship(back_populates="analyses")


class SoftwareComponentModel(Base):
    __tablename__ = "software_components"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "name", "kind", name="uq_software_analysis_name_kind"
        ),
    )

    software_component_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str | None] = mapped_column(String(255))
    digest: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("analysis_id", "uri", name="uq_artifact_analysis_uri"),
    )

    artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255))


class SequenceRunResultModel(Base):
    __tablename__ = "sequence_run_results"

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), primary_key=True
    )
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    run_accession: Mapped[str | None] = mapped_column(String(64))
    sample_accession: Mapped[str | None] = mapped_column(String(64))
    in_661k: Mapped[int | None] = mapped_column(Integer)
    in_ena_20240625: Mapped[int | None] = mapped_column(Integer)
    in_ena_20240801: Mapped[int | None] = mapped_column(Integer)
    in_ena_20250506: Mapped[int | None] = mapped_column(Integer)
    ena_202505_batch: Mapped[str | None] = mapped_column(String(64))
    fastq_md5: Mapped[str | None] = mapped_column(Text)
    meta_pass_atb: Mapped[int | None] = mapped_column(Integer)
    meta_pass_661k: Mapped[int | None] = mapped_column(Integer)
    pass_value: Mapped[int | None] = mapped_column("pass", Integer)
    comments: Mapped[str | None] = mapped_column(Text)


class AssemblyResultModel(Base):
    __tablename__ = "assembly_results"

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), primary_key=True
    )
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    sample_accession: Mapped[str | None] = mapped_column(String(64))
    run_accession: Mapped[str | None] = mapped_column(String(64))
    assembly_accession: Mapped[str | None] = mapped_column(String(64))
    assembly_seqkit_sum: Mapped[str | None] = mapped_column(Text)
    asm_pipe_filter: Mapped[str] = mapped_column(String(255), nullable=False)
    asm_fasta_on_osf: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dataset: Mapped[str] = mapped_column(String(64), default="local", nullable=False)
    scientific_name: Mapped[str | None] = mapped_column(Text)
    sylph_species_pre_202505: Mapped[str | None] = mapped_column(Text)
    in_hq_pre_202505: Mapped[str | None] = mapped_column(String(8))
    sylph_species: Mapped[str | None] = mapped_column(Text)
    sylph_filter: Mapped[str] = mapped_column(String(255), nullable=False)
    hq_filter: Mapped[str] = mapped_column(Text, nullable=False)
    osf_tarball_filename: Mapped[str | None] = mapped_column(Text)
    osf_tarball_url: Mapped[str | None] = mapped_column(Text)
    aws_url: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)
    assembly_uri: Mapped[str | None] = mapped_column(Text)
    assembly_sha256: Mapped[str | None] = mapped_column(String(64))


class AssemblyStatsResultModel(Base):
    __tablename__ = "assembly_stats_results"

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), primary_key=True
    )
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    sample_accession: Mapped[str | None] = mapped_column(String(64))
    total_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_length: Mapped[float] = mapped_column(Float, nullable=False)
    longest: Mapped[int] = mapped_column(Integer, nullable=False)
    shortest: Mapped[int] = mapped_column(Integer, nullable=False)
    n_count: Mapped[int] = mapped_column("N_count", BigInteger, nullable=False)
    gaps: Mapped[int] = mapped_column("Gaps", Integer, nullable=False)
    n50: Mapped[int] = mapped_column("N50", Integer, nullable=False)
    n50n: Mapped[int] = mapped_column("N50n", Integer, nullable=False)
    n70: Mapped[int] = mapped_column("N70", Integer, nullable=False)
    n70n: Mapped[int] = mapped_column("N70n", Integer, nullable=False)
    n90: Mapped[int] = mapped_column("N90", Integer, nullable=False)
    n90n: Mapped[int] = mapped_column("N90n", Integer, nullable=False)


class SylphResultModel(Base):
    __tablename__ = "sylph_results"

    sylph_result_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), nullable=False, index=True
    )
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    sample_accession: Mapped[str | None] = mapped_column(String(64))
    run_accession: Mapped[str | None] = mapped_column(String(64))
    genome_file: Mapped[str | None] = mapped_column("Genome_file", Text)
    taxonomic_abundance: Mapped[float | None] = mapped_column(
        "Taxonomic_abundance", Float
    )
    sequence_abundance: Mapped[float | None] = mapped_column(
        "Sequence_abundance", Float
    )
    adjusted_ani: Mapped[float | None] = mapped_column("Adjusted_ANI", Float)
    eff_cov: Mapped[float | None] = mapped_column("Eff_cov", Float)
    ani_5_95_percentile: Mapped[str | None] = mapped_column(
        "ANI_5_95_percentile", String(64)
    )
    eff_lambda: Mapped[float | None] = mapped_column("Eff_lambda", Float)
    lambda_5_95_percentile: Mapped[str | None] = mapped_column(
        "Lambda_5_95_percentile", String(64)
    )
    median_cov: Mapped[float | None] = mapped_column("Median_cov", Float)
    mean_cov_geq1: Mapped[float | None] = mapped_column("Mean_cov_geq1", Float)
    containment_ind: Mapped[str | None] = mapped_column("Containment_ind", String(64))
    naive_ani: Mapped[float | None] = mapped_column("Naive_ANI", Float)
    contig_name: Mapped[str | None] = mapped_column("Contig_name", Text)
    species: Mapped[str | None] = mapped_column("Species", Text)


class Checkm2ResultModel(Base):
    __tablename__ = "checkm2_results"

    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.analysis_id"), primary_key=True
    )
    sample_id: Mapped[str] = mapped_column(
        ForeignKey("samples.sample_id"), nullable=False, index=True
    )
    sample_accession: Mapped[str | None] = mapped_column(String(64))
    completeness_general: Mapped[float | None] = mapped_column(
        "Completeness_General", Float
    )
    contamination: Mapped[float | None] = mapped_column("Contamination", Float)
    completeness_specific: Mapped[float | None] = mapped_column(
        "Completeness_Specific", Float
    )
    completeness_model_used: Mapped[str | None] = mapped_column(
        "Completeness_Model_Used", Text
    )
    translation_table_used: Mapped[int | None] = mapped_column(
        "Translation_Table_Used", Integer
    )
    coding_density: Mapped[float | None] = mapped_column("Coding_Density", Float)
    contig_n50: Mapped[int | None] = mapped_column("Contig_N50", Integer)
    average_gene_length: Mapped[float | None] = mapped_column(
        "Average_Gene_Length", Float
    )
    genome_size: Mapped[int | None] = mapped_column("Genome_Size", BigInteger)
    gc_content: Mapped[float | None] = mapped_column("GC_Content", Float)
    total_coding_sequences: Mapped[int | None] = mapped_column(
        "Total_Coding_Sequences", Integer
    )
    additional_notes: Mapped[str | None] = mapped_column("Additional_Notes", Text)
