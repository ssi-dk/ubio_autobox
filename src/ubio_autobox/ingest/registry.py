"""Deep input registry for discovery, validation, fingerprinting, and registration."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ubio_autobox.domain.errors import InputValidationError, UbioAutoboxError
from ubio_autobox.domain.interfaces import ResultRepository
from ubio_autobox.domain.models import (
    FileDigest,
    FileRole,
    RegisteredSample,
    ValidatedSample,
)

SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
REQUIRED_COLUMNS = frozenset({"sample_key", "r1", "r2"})
KNOWN_COLUMNS = REQUIRED_COLUMNS | frozenset(
    {"insdc_sample_accession", "source_namespace", "source_record_id"}
)


@dataclass(frozen=True, slots=True)
class StabilityObservation:
    signature: str
    count: int


@dataclass(frozen=True, slots=True)
class StabilityCursor:
    observations: dict[str, StabilityObservation] = field(default_factory=dict)

    @classmethod
    def from_json(cls, value: str | None) -> StabilityCursor:
        if not value:
            return cls()
        try:
            raw = json.loads(value)
            observations = {
                str(key): StabilityObservation(
                    signature=str(item["signature"]), count=int(item["count"])
                )
                for key, item in raw.get("observations", {}).items()
            }
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return cls()
        return cls(observations=observations)

    def to_json(self) -> str:
        return json.dumps(
            {
                "observations": {
                    key: {"signature": item.signature, "count": item.count}
                    for key, item in sorted(self.observations.items())
                }
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    samples: tuple[RegisteredSample, ...]
    errors: tuple[str, ...]
    cursor: StabilityCursor


class FilesystemInputRegistry:
    """Own the complete landing-folder contract behind one interface."""

    def __init__(
        self,
        incoming_root: Path,
        repository: ResultRepository,
        stability_observations: int = 2,
    ) -> None:
        self._incoming_root = incoming_root.expanduser().resolve()
        self._repository = repository
        self._required_observations = stability_observations

    def discover_and_register(
        self, previous: StabilityCursor | None = None
    ) -> DiscoveryResult:
        previous = previous or StabilityCursor()
        current: dict[str, StabilityObservation] = {}
        registered: list[RegisteredSample] = []
        errors: list[str] = []

        if not self._incoming_root.exists():
            return DiscoveryResult((), (), StabilityCursor())

        batch_dirs = sorted(
            path for path in self._incoming_root.iterdir() if path.is_dir()
        )
        for batch_dir in batch_dirs:
            try:
                resolved_batch = batch_dir.resolve(strict=True)
                if not resolved_batch.is_relative_to(self._incoming_root):
                    raise InputValidationError("batch directory escapes incoming root")
            except (InputValidationError, OSError) as error:
                errors.append(f"{batch_dir.name}: {error}")
                continue
            manifest_path = batch_dir / "samples.csv"
            if not manifest_path.is_file():
                continue
            if not manifest_path.resolve().is_relative_to(resolved_batch):
                errors.append(
                    f"{batch_dir.name}: samples.csv escapes the batch directory"
                )
                continue
            try:
                rows, manifest_sha256 = self._read_manifest(manifest_path)
            except InputValidationError as error:
                errors.append(f"{batch_dir.name}: {error}")
                continue

            for row in rows:
                sample_key = row["sample_key"].strip()
                cursor_key = f"{batch_dir.name}/{sample_key}"
                ready_path = batch_dir / "samples" / sample_key / "READY"
                if not ready_path.is_file():
                    continue
                try:
                    if not ready_path.resolve(strict=True).is_relative_to(
                        resolved_batch
                    ):
                        raise InputValidationError(
                            "READY marker escapes the batch directory"
                        )
                    r1, r2 = self._resolve_read_paths(batch_dir, row)
                    signature = self._stability_signature(
                        manifest_sha256, ready_path, r1, r2
                    )
                except (InputValidationError, OSError) as error:
                    errors.append(f"{cursor_key}: {error}")
                    continue

                old = previous.observations.get(cursor_key)
                count = old.count + 1 if old and old.signature == signature else 1
                current[cursor_key] = StabilityObservation(signature, count)
                if count < self._required_observations:
                    continue

                try:
                    validated = self._validate_sample(
                        batch_dir,
                        manifest_path,
                        manifest_sha256,
                        row,
                        r1,
                        r2,
                    )
                    registered.append(self._repository.register_sample(validated))
                except (UbioAutoboxError, OSError) as error:
                    errors.append(f"{cursor_key}: {error}")

        return DiscoveryResult(
            samples=tuple(registered),
            errors=tuple(errors),
            cursor=StabilityCursor(current),
        )

    @staticmethod
    def _read_manifest(path: Path) -> tuple[list[dict[str, str]], str]:
        raw = path.read_bytes()
        manifest_sha256 = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise InputValidationError("samples.csv is not valid UTF-8") from error
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames is None:
            raise InputValidationError("samples.csv has no header")
        fields = {field.strip() for field in reader.fieldnames if field}
        missing = REQUIRED_COLUMNS - fields
        if missing:
            raise InputValidationError(
                f"samples.csv is missing required columns: {', '.join(sorted(missing))}"
            )

        rows: list[dict[str, str]] = []
        for row in reader:
            if None in row:
                raise InputValidationError(
                    "samples.csv row has more values than its header"
                )
            cleaned = {
                str(key).strip(): (value or "").strip() for key, value in row.items()
            }
            if any(cleaned.values()):
                rows.append(cleaned)
        keys = [row["sample_key"] for row in rows]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise InputValidationError(
                f"duplicate sample_key values: {', '.join(duplicates)}"
            )
        return rows, manifest_sha256

    @staticmethod
    def _resolve_read_paths(batch_dir: Path, row: dict[str, str]) -> tuple[Path, Path]:
        batch_root = batch_dir.resolve(strict=True)
        sample_key = row["sample_key"]
        if not SAFE_KEY.fullmatch(batch_dir.name):
            raise InputValidationError(f"unsafe batch key {batch_dir.name!r}")
        if not SAFE_KEY.fullmatch(sample_key):
            raise InputValidationError(f"unsafe sample key {sample_key!r}")

        paths: list[Path] = []
        for role in ("r1", "r2"):
            value = row[role]
            if not value:
                raise InputValidationError(f"{role} is empty")
            candidate = (batch_root / value).resolve(strict=True)
            if not candidate.is_relative_to(batch_root):
                raise InputValidationError(f"{role} escapes the batch directory")
            if not candidate.is_file():
                raise InputValidationError(f"{role} is not a regular file")
            paths.append(candidate)

        if paths[0] == paths[1]:
            raise InputValidationError("r1 and r2 refer to the same file")
        return paths[0], paths[1]

    @staticmethod
    def _stability_signature(
        manifest_sha256: str, ready_path: Path, r1: Path, r2: Path
    ) -> str:
        stats = [r1.stat(), r2.stat(), ready_path.stat()]
        payload = {
            "manifest_sha256": manifest_sha256,
            "r1": [stats[0].st_size, stats[0].st_mtime_ns],
            "r2": [stats[1].st_size, stats[1].st_mtime_ns],
            "ready": [stats[2].st_size, stats[2].st_mtime_ns],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _validate_sample(
        self,
        batch_dir: Path,
        manifest_path: Path,
        manifest_sha256: str,
        row: dict[str, str],
        r1: Path,
        r2: Path,
    ) -> ValidatedSample:
        self._validate_fastq(r1)
        self._validate_fastq(r2)
        r1_digest = self._digest(FileRole.R1, r1)
        r2_digest = self._digest(FileRole.R2, r2)

        source_namespace = row.get("source_namespace") or None
        source_record_id = row.get("source_record_id") or None
        if bool(source_namespace) is not bool(source_record_id):
            raise InputValidationError(
                "source_namespace and source_record_id must be supplied together"
            )

        canonical_row = json.dumps(row, sort_keys=True, separators=(",", ":"))
        row_sha256 = hashlib.sha256(canonical_row.encode()).hexdigest()
        fingerprint_payload = (
            f"{manifest_sha256}:{row_sha256}:{r1_digest.sha256}:{r2_digest.sha256}"
        )
        input_fingerprint = hashlib.sha256(fingerprint_payload.encode()).hexdigest()
        source_metadata = {
            key: value
            for key, value in row.items()
            if key not in KNOWN_COLUMNS and value
        }

        return ValidatedSample(
            batch_key=batch_dir.name,
            sample_key=row["sample_key"],
            manifest_path=manifest_path.resolve(),
            manifest_sha256=manifest_sha256,
            manifest_row_sha256=row_sha256,
            input_fingerprint=input_fingerprint,
            files=(r1_digest, r2_digest),
            insdc_sample_accession=row.get("insdc_sample_accession") or None,
            source_namespace=source_namespace,
            source_record_id=source_record_id,
            source_metadata=source_metadata,
        )

    @staticmethod
    def _validate_fastq(path: Path) -> None:
        try:
            with gzip.open(path, "rt", encoding="ascii") as handle:
                record_count = 0
                while True:
                    name = handle.readline()
                    if not name:
                        break
                    sequence = handle.readline()
                    separator = handle.readline()
                    quality = handle.readline()
                    if not sequence or not separator or not quality:
                        raise InputValidationError(
                            f"{path.name} contains a truncated FASTQ record"
                        )
                    name = name.rstrip()
                    sequence = sequence.rstrip()
                    separator = separator.rstrip()
                    quality = quality.rstrip()
                    if not name.startswith("@") or not separator.startswith("+"):
                        raise InputValidationError(
                            f"{path.name} has an invalid FASTQ record"
                        )
                    if not sequence or len(sequence) != len(quality):
                        raise InputValidationError(
                            f"{path.name} has mismatched sequence and quality lengths"
                        )
                    record_count += 1
        except (OSError, UnicodeDecodeError) as error:
            raise InputValidationError(
                f"{path.name} is not a readable gzip FASTQ"
            ) from error
        if record_count == 0:
            raise InputValidationError(f"{path.name} contains no FASTQ records")

    @staticmethod
    def _digest(role: FileRole, path: Path) -> FileDigest:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return FileDigest(
            role=role,
            path=path,
            sha256=digest.hexdigest(),
            size_bytes=path.stat().st_size,
        )
