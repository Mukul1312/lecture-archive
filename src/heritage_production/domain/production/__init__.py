"""Stable public API for the stdlib-only Production domain.

Release defines the gate, candidate, and eligibility concepts; Production owns
the data and is the only aggregate that appends a gate set, records a sign-off,
assembles a candidate, or approves a release. The gate and sign-off values are
re-exported here for callers that work in Production terms.
"""

from heritage_production.domain.release.gates import (
    ExternalGateRequirement,
    ExternalGateSet,
)
from heritage_production.domain.release.signoffs import (
    EXTERNAL_SIGN_OFF_OPERATION,
    ExternalSignOff,
    ExternalSignOffTarget,
    external_signoff_context_digest,
    external_signoff_intent_digest,
    gate_is_satisfied_by,
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
    "gate_is_satisfied_by",
]
