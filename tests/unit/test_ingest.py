from __future__ import annotations

import csv
from pathlib import Path

from tests.conftest import make_batch, write_fastq

from ubio_autobox.ingest import FilesystemInputRegistry, StabilityCursor
from ubio_autobox.persistence import SqlAlchemyResultRepository


def _repository(tmp_path: Path) -> SqlAlchemyResultRepository:
    repository = SqlAlchemyResultRepository(
        f"sqlite+pysqlite:///{tmp_path / 'results.sqlite'}"
    )
    repository.initialize()
    return repository


def test_ready_sample_is_stable_registered_and_idempotent(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    make_batch(incoming)
    repository = _repository(tmp_path)
    registry = FilesystemInputRegistry(incoming, repository, stability_observations=2)

    first = registry.discover_and_register()
    second = registry.discover_and_register(first.cursor)
    third = registry.discover_and_register(second.cursor)

    assert first.samples == ()
    assert len(second.samples) == 1
    assert second.samples[0].sample_id == third.samples[0].sample_id
    assert len(repository.list_samples()) == 1


def test_species_metadata_survives_registration_for_bactopia(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    make_batch(incoming, species="Staphylococcus aureus")
    repository = _repository(tmp_path)
    registry = FilesystemInputRegistry(incoming, repository, 1)

    registered = registry.discover_and_register().samples[0]
    reloaded = repository.get_registered_sample(registered.sample_id)

    assert reloaded.source_metadata["species"] == "Staphylococcus aureus"


def test_sample_without_ready_is_ignored(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    make_batch(incoming, ready=False)
    registry = FilesystemInputRegistry(incoming, _repository(tmp_path), 1)
    result = registry.discover_and_register()
    assert result.samples == ()
    assert result.errors == ()


def test_changed_ready_input_is_invalidated(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    batch = make_batch(incoming)
    repository = _repository(tmp_path)
    registry = FilesystemInputRegistry(incoming, repository, 2)
    initial = registry.discover_and_register(StabilityCursor())
    registered = registry.discover_and_register(initial.cursor)
    assert len(registered.samples) == 1

    write_fastq(
        batch / "samples" / "sample-001" / "reads_R1.fastq.gz",
        "ACGTACGTACGT",
    )
    changed_once = registry.discover_and_register(registered.cursor)
    changed_twice = registry.discover_and_register(changed_once.cursor)

    assert changed_twice.samples == ()
    assert "Ready input changed" in "\n".join(changed_twice.errors)
    assert repository.list_samples()[0]["status"] == "invalid"


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    batch = make_batch(incoming)
    outside = tmp_path / "outside.fastq.gz"
    write_fastq(outside)
    manifest = batch / "samples.csv"
    rows = list(csv.DictReader(manifest.read_text(encoding="utf-8").splitlines()))
    rows[0]["r1"] = "../../outside.fastq.gz"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    result = FilesystemInputRegistry(
        incoming, _repository(tmp_path), stability_observations=1
    ).discover_and_register()
    assert result.samples == ()
    assert "escapes the batch directory" in "\n".join(result.errors)
