"""Typed Narrator Voice domain and application-facing failures."""


class NarratorVoiceError(Exception):
    """Base for expected Narrator Voice failures."""


class DomainInvariantError(NarratorVoiceError):
    """A requested transition would violate an aggregate invariant."""


class RevisionConflict(NarratorVoiceError):
    """The supplied optimistic revision is stale."""


class AuthorizationDenied(NarratorVoiceError):
    """The current actor/status does not authorize an operation."""


class NotFound(NarratorVoiceError):
    """A requested aggregate or immutable child identity is absent."""


class BudgetDenied(NarratorVoiceError):
    """A generation reservation exceeds its explicit cap."""


class ExternalWorkError(NarratorVoiceError):
    """Base for classified outbound-work failures."""


class DefinitePreSendFailure(ExternalWorkError):
    """Evidence proves no provider request was sent."""


class AmbiguousExternalFailure(ExternalWorkError):
    """Evidence cannot prove whether provider work completed."""


class ExternalWorkFailed(ExternalWorkError):
    """External work definitively failed after submission."""
