from __future__ import annotations

import csv
from pathlib import Path

from ubio_autobox.ingest import FilesystemInputRegistry, create_synthetic_batch
from ubio_autobox.persistence import SqlAlchemyResultRepository


def test_synthetic_batch_matches_landing_contract(tmp_path: Path) -> None:
    batch = create_synthetic_batch(
        tmp_path / "incoming",
        sample_count=3,
        batch_key="synthetic-test",
        species="Staphylococcus aureus",
    )

    assert batch.sample_keys == (
        "synthetic-0001",
        "synthetic-0002",
        "synthetic-0003",
    )
    rows = list(
        csv.DictReader(
            (batch.path / "samples.csv").read_text(encoding="utf-8").splitlines()
        )
    )
    assert len(rows) == 3
    assert rows[0]["species"] == "Staphylococcus aureus"
    for sample_key in batch.sample_keys:
        sample_dir = batch.path / "samples" / sample_key
        assert (sample_dir / "reads_R1.fastq.gz").is_file()
        assert (sample_dir / "reads_R2.fastq.gz").is_file()
        assert (sample_dir / "READY").is_file()


def test_synthetic_batch_registers_immediately(tmp_path: Path) -> None:
    batch = create_synthetic_batch(tmp_path / "incoming")
    repository = SqlAlchemyResultRepository(
        f"sqlite+pysqlite:///{tmp_path / 'results.sqlite'}"
    )
    repository.initialize()

    result = FilesystemInputRegistry(
        batch.path.parent,
        repository,
        stability_observations=1,
    ).discover_and_register()

    assert len(result.samples) == 1
    assert result.samples[0].source_metadata["synthetic"] == "true"
