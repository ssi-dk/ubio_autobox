"""Domain-specific failures with stable meanings for callers."""


class UbioAutoboxError(Exception):
    """Base class for expected application failures."""


class InputValidationError(UbioAutoboxError):
    """A landing sample does not satisfy the input contract."""


class ImmutableInputError(UbioAutoboxError):
    """A previously registered input changed after it became ready."""


class AnalysisNotFoundError(UbioAutoboxError):
    """The requested analysis does not exist."""


class AnalysisAlreadyCompletedError(UbioAutoboxError):
    """An immutable successful analysis already exists for this configuration."""


class ExecutionFailedError(UbioAutoboxError):
    """A scientific workflow command failed."""


class OutputParseError(UbioAutoboxError):
    """Required workflow outputs are absent or malformed."""
