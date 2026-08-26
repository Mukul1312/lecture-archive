"""Application-owned failure vocabulary.

The domain owns validation, invariant, staleness, and policy errors. These
three are application concerns: idempotency conflicts (design 9.4), replay
records that stored state can no longer reproduce, and violations of the
one-root transaction rule (design 9.3). Infrastructure adapters raise them
too, so a handler never sees a SQL or filesystem exception.
"""


class ApplicationError(Exception):
    """Base class for expected application-layer failures."""


class OperationConflictError(ApplicationError):
    """An operation id was reused with different inputs, or recorded twice."""


class ReplayIntegrityError(ApplicationError):
    """A stored operation record is inconsistent with current stored state."""


class TransactionRuleError(ApplicationError):
    """A write violated the one-transaction-one-aggregate-root rule."""
