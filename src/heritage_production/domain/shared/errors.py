"""Domain-owned error categories."""


class DomainError(Exception):
    """Base class for expected domain failures."""


class ValidationError(DomainError, ValueError):
    """A supplied value is not in the domain's accepted representation."""


class InvariantError(DomainError):
    """A requested transition would violate a domain invariant."""


class StaleReferenceError(DomainError):
    """A supplied immutable reference no longer matches current state."""


class PolicyRefusalError(DomainError):
    """A policy explicitly refuses an otherwise well-formed operation."""
