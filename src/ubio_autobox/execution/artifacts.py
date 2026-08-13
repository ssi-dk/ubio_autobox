"""Local/shared-filesystem artifact storage with atomic publication."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ubio_autobox.domain.errors import ImmutableInputError
from ubio_autobox.domain.models import ArtifactRef


class LocalArtifactStore:
    """Own staging and immutable publication under a configured root."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    def allocate_attempt(
        self, sample_id: UUID, analysis_id: UUID, attempt: int
    ) -> Path:
        analysis_root = (
            self._root / "samples" / str(sample_id) / "analyses" / str(analysis_id)
        )
        staging = analysis_root / "staging" / f"attempt-{attempt:04d}"
        if staging.exists():
            raise ImmutableInputError(f"Attempt workspace already exists: {staging}")
        staging.mkdir(parents=True)
        return staging

    def seed_attempt_from_workspace(self, source: Path, target: Path) -> None:
        """Copy the prior Bactopia tree into a new resumable attempt."""

        source = source.expanduser().resolve(strict=True)
        target = target.expanduser().resolve()
        if not source.is_relative_to(self._root):
            raise ImmutableInputError(f"Resume source escapes artifact root: {source}")
        source_bactopia = source / "bactopia"
        if not source_bactopia.is_dir():
            raise ImmutableInputError(
                f"Resume checkpoint has no Bactopia output tree: {source_bactopia}"
            )
        target.mkdir(parents=True, exist_ok=True)
        destination = target / "bactopia"
        if destination.exists():
            raise ImmutableInputError(
                f"Resume destination already exists: {destination}"
            )
        shutil.copytree(source_bactopia, destination)

    def publish_tree(self, analysis_id: UUID, root: Path) -> tuple[ArtifactRef, ...]:
        root = root.resolve(strict=True)
        if root.parent.name != "staging":
            raise ValueError("Only an allocated staging directory can be published")
        for path in root.rglob("*"):
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError(f"Artifact escapes its staging directory: {path}")

        published = root.parent.parent / "published" / root.name
        published.parent.mkdir(parents=True, exist_ok=True)
        if published.exists():
            raise ImmutableInputError(f"Published attempt already exists: {published}")
        root.rename(published)

        return tuple(
            self._artifact_for(analysis_id, path, published)
            for path in sorted(item for item in published.rglob("*") if item.is_file())
        )

    def retain_failure(self, root: Path) -> Path:
        root = root.resolve(strict=True)
        if root.parent.name != "staging":
            return root
        retained = root.parent.parent / "failed" / root.name
        retained.parent.mkdir(parents=True, exist_ok=True)
        if retained.exists():
            raise ImmutableInputError(
                f"Failed attempt destination already exists: {retained}"
            )
        root.rename(retained)
        return retained

    def published_attempt_uri(self, analysis_id: UUID, attempt: int) -> str:
        """Return the stable URI for a successfully published attempt."""

        matches = list(self._root.glob(f"samples/*/analyses/{analysis_id}"))
        if len(matches) != 1:
            raise ImmutableInputError(
                f"Could not resolve published analysis root for {analysis_id}"
            )
        return (matches[0] / "published" / f"attempt-{attempt:04d}").resolve().as_uri()

    @staticmethod
    def _artifact_for(
        analysis_id: UUID, path: Path, published_root: Path
    ) -> ArtifactRef:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        relative = path.relative_to(published_root)
        return ArtifactRef(
            artifact_id=uuid4(),
            analysis_id=analysis_id,
            kind=LocalArtifactStore._artifact_kind(relative),
            uri=path.as_uri(),
            sha256=digest.hexdigest(),
            size_bytes=path.stat().st_size,
            media_type=mimetypes.guess_type(path.name)[0],
        )

    @staticmethod
    def _artifact_kind(path: Path) -> str:
        name = path.name.lower()
        if name.endswith((".fna", ".fna.gz", ".fa", ".fa.gz", ".fasta.gz")):
            return "assembly"
        if path.parts and path.parts[0] == "logs":
            return "log"
        if path.parts and path.parts[0] == "exports":
            return "export"
        if name.endswith((".tsv", ".csv", ".json")):
            return "result"
        return "bactopia_output"


class AttemptManifest:
    """Write the structured, human- and machine-readable attempt record."""

    def __init__(self, root: Path, initial: dict[str, Any]) -> None:
        self._path = root / "attempt-manifest.json"
        self._data = dict(initial)
        self.update()

    @property
    def path(self) -> Path:
        return self._path

    def update(self, **values: Any) -> None:
        self._data.update(values)
        self._data["updated_at"] = datetime.now(UTC).isoformat()
        self._path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )


def inventory_files(
    root: Path, *, exclude: set[Path] | None = None
) -> list[dict[str, Any]]:
    """Return checksummed relative file metadata for an attempt manifest."""

    excluded = {path.resolve() for path in (exclude or set())}
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.resolve() not in excluded
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
