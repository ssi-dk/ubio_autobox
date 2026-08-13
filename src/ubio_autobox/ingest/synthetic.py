"""Fast, disposable input batches for smoke tests and local demonstrations."""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .registry import SAFE_KEY


@dataclass(frozen=True, slots=True)
class SyntheticBatch:
    path: Path
    sample_keys: tuple[str, ...]


def create_synthetic_batch(
    incoming_root: Path,
    *,
    sample_count: int = 1,
    batch_key: str | None = None,
    sample_prefix: str = "synthetic",
    species: str = "Escherichia coli",
) -> SyntheticBatch:
    """Create tiny valid paired FASTQs and commit them with READY markers."""

    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")
    resolved_batch_key = batch_key or f"synthetic-{uuid4().hex[:10]}"
    _validate_key(resolved_batch_key, "batch_key")
    _validate_key(sample_prefix, "sample_prefix")
    batch = incoming_root.expanduser().resolve() / resolved_batch_key
    if batch.exists():
        raise FileExistsError(f"Synthetic batch already exists: {batch}")

    samples_root = batch / "samples"
    samples_root.mkdir(parents=True)
    sample_keys = tuple(
        f"{sample_prefix}-{index:04d}" for index in range(1, sample_count + 1)
    )
    for sample_key in sample_keys:
        _validate_key(sample_key, "sample_key")
        sample_dir = samples_root / sample_key
        _write_fastq(sample_dir / "reads_R1.fastq.gz", "ACGTACGT", sample_key)
        _write_fastq(sample_dir / "reads_R2.fastq.gz", "TGCATGCA", sample_key)

    manifest = batch / "samples.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_key",
                "r1",
                "r2",
                "insdc_sample_accession",
                "source_namespace",
                "source_record_id",
                "species",
                "synthetic",
            ],
        )
        writer.writeheader()
        for sample_key in sample_keys:
            writer.writerow(
                {
                    "sample_key": sample_key,
                    "r1": f"samples/{sample_key}/reads_R1.fastq.gz",
                    "r2": f"samples/{sample_key}/reads_R2.fastq.gz",
                    "insdc_sample_accession": "",
                    "source_namespace": "",
                    "source_record_id": "",
                    "species": species,
                    "synthetic": "true",
                }
            )

    # READY is the commit marker: write it only after every file and the
    # manifest are complete, matching the real landing-folder contract.
    for sample_key in sample_keys:
        (samples_root / sample_key / "READY").touch()
    return SyntheticBatch(batch, sample_keys)


def _write_fastq(path: Path, sequence: str, sample_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="ascii") as handle:
        handle.write(f"@{sample_key}/synthetic\n{sequence}\n+\n{'I' * len(sequence)}\n")


def _validate_key(value: str, field_name: str) -> None:
    if not SAFE_KEY.fullmatch(value):
        raise ValueError(f"{field_name} must match {SAFE_KEY.pattern}")
