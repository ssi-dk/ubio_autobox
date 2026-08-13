"""Domain types and interfaces."""

from .models import (
    AnalysisRequest,
    AnalysisStatus,
    ArtifactRef,
    BactopiaRequest,
    ExecutionPhase,
    ExecutionResult,
    FileDigest,
    FileRole,
    NormalizedResultSet,
    PhaseStatus,
    RegisteredSample,
    ValidatedSample,
)

__all__ = [
    "AnalysisRequest",
    "AnalysisStatus",
    "ArtifactRef",
    "BactopiaRequest",
    "ExecutionResult",
    "ExecutionPhase",
    "FileDigest",
    "FileRole",
    "NormalizedResultSet",
    "PhaseStatus",
    "RegisteredSample",
    "ValidatedSample",
]
