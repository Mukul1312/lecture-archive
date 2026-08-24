"""Stable public API for the stdlib-only Release domain."""

from .policy import (
    BASIS_POINTS_MAX,
    BlockingFindingRule,
    IntegrityCheckCode,
    ReleasePolicyRules,
    ReleasePolicyVersion,
    ReviewCoverageRequirement,
    SignOffRequirement,
    UncertaintyAllowance,
    UncertaintyLimitMetric,
)
from .assessment import (
    EligibilityAssessment,
    EligibilityAssessmentRef,
    GateOutcome,
    GateResult,
    GateType,
)
from .gates import ExternalGateRequirement, ExternalGateSet
from .canonical import credential_key
from .signoffs import (
    EXTERNAL_SIGN_OFF_OPERATION,
    ExternalSignOff,
    ExternalSignOffTarget,
    external_signoff_context_digest,
    external_signoff_intent_digest,
    gate_is_satisfied_by,
)
from .content import (
    ReleaseCandidateSnapshot,
    ReleaseContentBinding,
    ReleaseMember,
)
from .eligibility import (
    SUPPORTED_EVALUATOR_REF,
    EligibilityInputSnapshot,
    IntegrityCheckResult,
    ReleaseEligibilityEvaluator,
    ResolvedSignOffRequirement,
    SelectedEditionEvidence,
    TranscriptScopeAssessment,
    UncertaintyObservation,
    resolve_sign_off_requirements,
)

__all__ = [
    "BASIS_POINTS_MAX",
    "SUPPORTED_EVALUATOR_REF",
    "EXTERNAL_SIGN_OFF_OPERATION",
    "ExternalGateRequirement",
    "ExternalGateSet",
    "ExternalSignOff",
    "ExternalSignOffTarget",
    "external_signoff_context_digest",
    "external_signoff_intent_digest",
    "gate_is_satisfied_by",
    "BlockingFindingRule",
    "EligibilityAssessment",
    "EligibilityAssessmentRef",
    "EligibilityInputSnapshot",
    "GateOutcome",
    "GateResult",
    "GateType",
    "IntegrityCheckCode",
    "IntegrityCheckResult",
    "ReleaseCandidateSnapshot",
    "ReleaseContentBinding",
    "ReleaseMember",
    "ReleasePolicyRules",
    "ReleaseEligibilityEvaluator",
    "ReleasePolicyVersion",
    "ResolvedSignOffRequirement",
    "SelectedEditionEvidence",
    "TranscriptScopeAssessment",
    "UncertaintyObservation",
    "resolve_sign_off_requirements",
    "ReviewCoverageRequirement",
    "SignOffRequirement",
    "UncertaintyAllowance",
    "UncertaintyLimitMetric",
]
