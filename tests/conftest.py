from __future__ import annotations

import csv
import gzip
from pathlib import Path

import pytest

from ubio_autobox.config import (
    AppSettings,
    BactopiaSettings,
    DatabaseSettings,
    PathsSettings,
)


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        paths=PathsSettings(
            incoming_root=tmp_path / "incoming",
            artifact_root=tmp_path / "artifacts",
            cache_root=tmp_path / "cache",
        ),
        database=DatabaseSettings(
            url=f"sqlite+pysqlite:///{tmp_path / 'results.sqlite'}"
        ),
        bactopia=BactopiaSettings(runner="fake"),
    )


def write_fastq(path: Path, sequence: str = "ACGTACGT") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="ascii") as handle:
        handle.write(f"@read\n{sequence}\n+\n{'I' * len(sequence)}\n")


def make_batch(
    incoming: Path,
    *,
    batch_key: str = "batch-001",
    sample_key: str = "sample-001",
    ready: bool = True,
    sample_accession: str = "",
    source_namespace: str = "",
    source_record_id: str = "",
) -> Path:
    batch = incoming / batch_key
    sample_dir = batch / "samples" / sample_key
    write_fastq(sample_dir / "reads_R1.fastq.gz")
    write_fastq(sample_dir / "reads_R2.fastq.gz", "TGCATGCA")
    if ready:
        (sample_dir / "READY").touch()
    batch.mkdir(parents=True, exist_ok=True)
    with (batch / "samples.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_key",
                "r1",
                "r2",
                "insdc_sample_accession",
                "source_namespace",
                "source_record_id",
                "lab_note",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_key": sample_key,
                "r1": f"samples/{sample_key}/reads_R1.fastq.gz",
                "r2": f"samples/{sample_key}/reads_R2.fastq.gz",
                "insdc_sample_accession": sample_accession,
                "source_namespace": source_namespace,
                "source_record_id": source_record_id,
                "lab_note": "synthetic",
            }
        )
    return batch
