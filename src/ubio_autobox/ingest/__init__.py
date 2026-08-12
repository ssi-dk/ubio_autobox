"""Landing-folder ingestion module."""

from .registry import (
    DiscoveryResult,
    FilesystemInputRegistry,
    StabilityCursor,
)
from .synthetic import SyntheticBatch, create_synthetic_batch

__all__ = [
    "DiscoveryResult",
    "FilesystemInputRegistry",
    "StabilityCursor",
    "SyntheticBatch",
    "create_synthetic_batch",
]
