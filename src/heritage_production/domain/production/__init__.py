"""Stable public API for the stdlib-only Production domain."""

from .gates import ExternalGateRequirement, ExternalGateSet
from .signoffs import (
    EXTERNAL_SIGN_OFF_OPERATION,
    ExternalSignOff,
    ExternalSignOffTarget,
    external_signoff_context_digest,
    external_signoff_intent_digest,
)
from .sources import AttachedSource, EditionSelection
from .approval import ApprovalEvidence, ReleaseApproval
from .aggregate import Production

__all__ = [
    "EXTERNAL_SIGN_OFF_OPERATION",
    "ApprovalEvidence",
    "AttachedSource",
    "EditionSelection",
    "ExternalGateRequirement",
    "ExternalGateSet",
    "ExternalSignOff",
    "ExternalSignOffTarget",
    "Production",
    "ReleaseApproval",
    "external_signoff_context_digest",
    "external_signoff_intent_digest",
]
