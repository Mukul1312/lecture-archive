"""Expected validation failures for generic kernel values."""


class _DomainError(Exception):
    """Private base for expected domain failures."""


class ValidationError(_DomainError, ValueError):
    """A supplied value is not in the accepted representation."""
