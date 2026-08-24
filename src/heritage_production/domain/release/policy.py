"""Immutable release-policy versions and their complete normalized rule set."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from heritage_production.domain.review import FindingCategoryCode, FindingSeverityCode
from heritage_production.domain.shared import (
    ActorId,
    AssuranceLevel,
    ContentDigest,
    GateScope,
    JsonValue,
    ManifestMemberRole,
    PolicyEvaluatorRef,
    PolicyRef,
    ReleasePolicyVersionId,
    RoleCode,
    SignOffTargetKind,
    SignOffTargetRule,
    ValidationError,
    semantic_digest,
)
from heritage_production.domain.shared.text import require_canonical_text
from heritage_production.domain.transcription import UncertaintyKind


BASIS_POINTS_MAX = 10_000


def _digest_value(value: ContentDigest) -> dict[str, JsonValue]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def _evaluator_value(value: PolicyEvaluatorRef) -> dict[str, JsonValue]:
    return {
        "evaluator_name": value.evaluator_name,
        "semantic_version": value.semantic_version,
        "supported_policy_schema": value.supported_policy_schema,
        "implementation_build_digest": _digest_value(value.implementation_build_digest),
    }


def _require_canonical_unique(
    values: tuple[object, ...],
    *,
    field: str,
    expected_type: type[object],
    key: object,
) -> None:
    if type(values) is not tuple or not all(type(value) is expected_type for value in values):
        raise ValidationError(
            f"{field} must be an immutable tuple of {expected_type.__name__}"
        )
    keys = tuple(key(value) for value in values)  # type: ignore[operator]
    if keys != tuple(sorted(keys)):
        raise ValidationError(f"{field} must already be in canonical order")
    if len(set(keys)) != len(keys):
        raise ValidationError(f"{field} must not contain duplicate semantic keys")


@dataclass(frozen=True, slots=True)
class IntegrityCheckCode:
    value: str

    def __post_init__(self) -> None:
        require_canonical_text(self.value, field="integrity check code", nonempty=True)

    def __str__(self) -> str:
        return self.value


class UncertaintyLimitMetric(str, Enum):
    MARK_COUNT = "mark_count"
    SOURCE_DURATION_US = "source_duration_us"
    CHARACTER_COUNT = "character_count"


@dataclass(frozen=True, slots=True)
class UncertaintyAllowance:
    """One permitted uncertainty kind with an explicit inclusive maximum."""

    kind: UncertaintyKind
    metric: UncertaintyLimitMetric
    maximum: int

    def __post_init__(self) -> None:
        if type(self.kind) is not UncertaintyKind:
            raise ValidationError("kind must be an exact UncertaintyKind")
        if type(self.metric) is not UncertaintyLimitMetric:
            raise ValidationError("metric must be an exact UncertaintyLimitMetric")
        if type(self.maximum) is not int or self.maximum < 0:
            raise ValidationError("uncertainty maximum must be a nonnegative integer")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "metric": self.metric.value,
            "maximum": self.maximum,
        }


@dataclass(frozen=True, slots=True)
class BlockingFindingRule:
    """An explicit category plus severity set; no severity ordering is implied."""

    category_code: FindingCategoryCode
    severity_codes: tuple[FindingSeverityCode, ...]

    def __post_init__(self) -> None:
        if type(self.category_code) is not FindingCategoryCode:
            raise ValidationError("category_code must be an exact FindingCategoryCode")
        _require_canonical_unique(
            self.severity_codes,
            field="severity_codes",
            expected_type=FindingSeverityCode,
            key=lambda value: value.value,
        )
        if not self.severity_codes:
            raise ValidationError("a blocking finding rule requires at least one severity")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "category_code": self.category_code.value,
            "severity_codes": [value.value for value in self.severity_codes],
        }


@dataclass(frozen=True, slots=True)
class ReviewCoverageRequirement:
    role: RoleCode
    minimum_basis_points: int
    require_complete_submission: bool

    def __post_init__(self) -> None:
        if type(self.role) is not RoleCode:
            raise ValidationError("role must be an exact RoleCode")
        if (
            type(self.minimum_basis_points) is not int
            or not 0 <= self.minimum_basis_points <= BASIS_POINTS_MAX
        ):
            raise ValidationError(
                "minimum_basis_points must be an integer between 0 and 10000 inclusive"
            )
        if type(self.require_complete_submission) is not bool:
            raise ValidationError("require_complete_submission must be a boolean")

    def payload(self) -> dict[str, JsonValue]:
        return {
            "role": self.role.value,
            "minimum_basis_points": self.minimum_basis_points,
            "require_complete_submission": self.require_complete_submission,
        }


@dataclass(frozen=True, slots=True)
class SignOffRequirement:
    """A policy-declared sign-off gate; policy never pins an individual actor."""

    scope: GateScope
    role: RoleCode
    target_kind: SignOffTargetKind
    required_member_role: ManifestMemberRole | None
    minimum_assurance: AssuranceLevel
    required_count: int

    def __post_init__(self) -> None:
        if type(self.scope) is not GateScope:
            raise ValidationError("scope must be an exact GateScope")
        if type(self.role) is not RoleCode:
            raise ValidationError("role must be an exact RoleCode")
        target_rule = SignOffTargetRule(self.target_kind, self.required_member_role)
        if not target_rule.permits_scope(self.scope):
            raise ValidationError("sign-off target kind does not belong to its gate scope")
        if type(self.minimum_assurance) is not AssuranceLevel:
            raise ValidationError("minimum_assurance must be an exact AssuranceLevel")
        if self.minimum_assurance is AssuranceLevel.UNVERIFIED:
            raise ValidationError("canonical sign-off gates require at least attestation")
        if type(self.required_count) is not int or self.required_count <= 0:
            raise ValidationError("required_count must be a positive integer")

    @property
    def target_rule(self) -> SignOffTargetRule:
        return SignOffTargetRule(self.target_kind, self.required_member_role)

    @property
    def semantic_key(self) -> tuple[str, str, str, str]:
        return (
            self.scope.value,
            self.role.value,
            self.target_kind.value,
            self.required_member_role.value if self.required_member_role else "",
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "scope": self.scope.value,
            "role": self.role.value,
            "target_kind": self.target_kind.value,
            "required_member_role": (
                self.required_member_role.value
                if self.required_member_role is not None
                else None
            ),
            "minimum_assurance": self.minimum_assurance.value,
            "required_count": self.required_count,
        }


@dataclass(frozen=True, slots=True)
class ReleasePolicyRules:
    """The complete normalized rule set; no field is silently defaulted."""

    required_integrity_checks: tuple[IntegrityCheckCode, ...]
    uncertainty_allowances: tuple[UncertaintyAllowance, ...]
    blocking_finding_rules: tuple[BlockingFindingRule, ...]
    review_coverage_requirements: tuple[ReviewCoverageRequirement, ...]
    review_signoff_requirements: tuple[SignOffRequirement, ...]
    external_signoff_requirements: tuple[SignOffRequirement, ...]
    required_release_members: tuple[ManifestMemberRole, ...]
    maximum_unresolved_findings: int

    def __post_init__(self) -> None:
        _require_canonical_unique(
            self.required_integrity_checks,
            field="required_integrity_checks",
            expected_type=IntegrityCheckCode,
            key=lambda value: value.value,
        )
        _require_canonical_unique(
            self.uncertainty_allowances,
            field="uncertainty_allowances",
            expected_type=UncertaintyAllowance,
            key=lambda value: value.kind.value,
        )
        _require_canonical_unique(
            self.blocking_finding_rules,
            field="blocking_finding_rules",
            expected_type=BlockingFindingRule,
            key=lambda value: value.category_code.value,
        )
        _require_canonical_unique(
            self.review_coverage_requirements,
            field="review_coverage_requirements",
            expected_type=ReviewCoverageRequirement,
            key=lambda value: value.role.value,
        )
        _require_canonical_unique(
            self.review_signoff_requirements,
            field="review_signoff_requirements",
            expected_type=SignOffRequirement,
            key=lambda value: value.semantic_key,
        )
        _require_canonical_unique(
            self.external_signoff_requirements,
            field="external_signoff_requirements",
            expected_type=SignOffRequirement,
            key=lambda value: value.semantic_key,
        )
        _require_canonical_unique(
            self.required_release_members,
            field="required_release_members",
            expected_type=ManifestMemberRole,
            key=lambda value: value.value,
        )
        if any(
            value.scope is not GateScope.REVIEW for value in self.review_signoff_requirements
        ):
            raise ValidationError("review sign-off requirements must use the REVIEW scope")
        if any(
            value.scope is not GateScope.EXTERNAL_RELEASE
            for value in self.external_signoff_requirements
        ):
            raise ValidationError(
                "external sign-off requirements must use the EXTERNAL_RELEASE scope"
            )
        if (
            type(self.maximum_unresolved_findings) is not int
            or self.maximum_unresolved_findings < 0
        ):
            raise ValidationError(
                "maximum_unresolved_findings must be a nonnegative integer"
            )

    def validated(self) -> "ReleasePolicyRules":
        """Reconstruct every rule value through its own constructor."""
        return ReleasePolicyRules(
            required_integrity_checks=tuple(
                IntegrityCheckCode(value.value)
                for value in self.required_integrity_checks
            ),
            uncertainty_allowances=tuple(
                UncertaintyAllowance(value.kind, value.metric, value.maximum)
                for value in self.uncertainty_allowances
            ),
            blocking_finding_rules=tuple(
                BlockingFindingRule(
                    FindingCategoryCode(value.category_code.value),
                    tuple(
                        FindingSeverityCode(code.value)
                        for code in value.severity_codes
                    ),
                )
                for value in self.blocking_finding_rules
            ),
            review_coverage_requirements=tuple(
                ReviewCoverageRequirement(
                    RoleCode(value.role.value),
                    value.minimum_basis_points,
                    value.require_complete_submission,
                )
                for value in self.review_coverage_requirements
            ),
            review_signoff_requirements=tuple(
                _revalidate_requirement(value)
                for value in self.review_signoff_requirements
            ),
            external_signoff_requirements=tuple(
                _revalidate_requirement(value)
                for value in self.external_signoff_requirements
            ),
            required_release_members=tuple(
                ManifestMemberRole(value.value)
                for value in self.required_release_members
            ),
            maximum_unresolved_findings=self.maximum_unresolved_findings,
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "required_integrity_checks": [
                value.value for value in self.required_integrity_checks
            ],
            "uncertainty_allowances": [
                value.payload() for value in self.uncertainty_allowances
            ],
            "blocking_finding_rules": [
                value.payload() for value in self.blocking_finding_rules
            ],
            "review_coverage_requirements": [
                value.payload() for value in self.review_coverage_requirements
            ],
            "review_signoff_requirements": [
                value.payload() for value in self.review_signoff_requirements
            ],
            "external_signoff_requirements": [
                value.payload() for value in self.external_signoff_requirements
            ],
            "required_release_members": [
                value.value for value in self.required_release_members
            ],
            "maximum_unresolved_findings": self.maximum_unresolved_findings,
        }


def _revalidate_requirement(value: "SignOffRequirement") -> "SignOffRequirement":
    if type(value) is not SignOffRequirement:
        raise ValidationError("a sign-off requirement must be an exact value")
    return SignOffRequirement(
        value.scope,
        RoleCode(value.role.value),
        value.target_kind,
        (
            ManifestMemberRole(value.required_member_role.value)
            if value.required_member_role is not None
            else None
        ),
        value.minimum_assurance,
        value.required_count,
    )


def _policy_payload(
    semantic_label: str,
    policy_schema_version: int,
    policy_schema_code: str,
    evaluator_ref: PolicyEvaluatorRef,
    rules: ReleasePolicyRules,
    author_actor_id: ActorId,
) -> dict[str, JsonValue]:
    return {
        "semantic_label": semantic_label,
        "policy_schema_version": policy_schema_version,
        "policy_schema_code": policy_schema_code,
        "evaluator_ref": _evaluator_value(evaluator_ref),
        "rules": rules.payload(),
        "author_actor_id": author_actor_id.value,
    }


@dataclass(frozen=True, slots=True)
class ReleasePolicyVersion:
    """A sealed, immutable policy version bound to one exact evaluator."""

    release_policy_version_id: ReleasePolicyVersionId
    semantic_label: str
    policy_schema_version: int
    policy_schema_code: str
    evaluator_ref: PolicyEvaluatorRef
    rules: ReleasePolicyRules
    author_actor_id: ActorId
    created_at_us: int
    policy_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            (
                "release_policy_version_id",
                self.release_policy_version_id,
                ReleasePolicyVersionId,
            ),
            ("evaluator_ref", self.evaluator_ref, PolicyEvaluatorRef),
            ("rules", self.rules, ReleasePolicyRules),
            ("author_actor_id", self.author_actor_id, ActorId),
            ("policy_digest", self.policy_digest, ContentDigest),
        ):
            if type(value) is not expected:
                raise ValidationError(f"{field_name} must be an exact {expected.__name__}")
        require_canonical_text(self.semantic_label, field="semantic_label", nonempty=True)
        require_canonical_text(
            self.policy_schema_code, field="policy_schema_code", nonempty=True
        )
        if type(self.policy_schema_version) is not int or self.policy_schema_version <= 0:
            raise ValidationError("policy_schema_version must be a positive integer")
        if type(self.created_at_us) is not int or self.created_at_us <= 0:
            raise ValidationError("created_at_us must be a positive integer")
        if self.policy_schema_code != self.evaluator_ref.supported_policy_schema:
            raise ValidationError(
                "policy schema code is incompatible with its pinned evaluator"
            )
        expected_digest = semantic_digest(
            "heritage-release-policy-v1", self.rules_payload()
        )
        if expected_digest != self.policy_digest:
            raise ValidationError("release-policy digest does not match its rule set")

    @classmethod
    def seal(
        cls,
        *,
        release_policy_version_id: ReleasePolicyVersionId,
        semantic_label: str,
        policy_schema_version: int,
        policy_schema_code: str,
        evaluator_ref: PolicyEvaluatorRef,
        rules: ReleasePolicyRules,
        author_actor_id: ActorId,
        created_at_us: int,
    ) -> ReleasePolicyVersion:
        try:
            digest = semantic_digest(
                "heritage-release-policy-v1",
                _policy_payload(
                    semantic_label,
                    policy_schema_version,
                    policy_schema_code,
                    evaluator_ref,
                    rules,
                    author_actor_id,
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed release-policy semantic input") from error
        return cls(
            release_policy_version_id,
            semantic_label,
            policy_schema_version,
            policy_schema_code,
            evaluator_ref,
            rules,
            author_actor_id,
            created_at_us,
            digest,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        release_policy_version_id: ReleasePolicyVersionId,
        semantic_label: str,
        policy_schema_version: int,
        policy_schema_code: str,
        evaluator_ref: PolicyEvaluatorRef,
        rules: ReleasePolicyRules,
        author_actor_id: ActorId,
        created_at_us: int,
        policy_digest: ContentDigest,
    ) -> ReleasePolicyVersion:
        return cls(
            release_policy_version_id,
            semantic_label,
            policy_schema_version,
            policy_schema_code,
            evaluator_ref,
            rules,
            author_actor_id,
            created_at_us,
            policy_digest,
        )

    def validated(self) -> ReleasePolicyVersion:
        """Reconstruct this policy and every reachable rule value."""
        return type(self).reconstitute(
            release_policy_version_id=ReleasePolicyVersionId(
                self.release_policy_version_id.value
            ),
            semantic_label=self.semantic_label,
            policy_schema_version=self.policy_schema_version,
            policy_schema_code=self.policy_schema_code,
            evaluator_ref=PolicyEvaluatorRef(
                self.evaluator_ref.evaluator_name,
                self.evaluator_ref.semantic_version,
                self.evaluator_ref.supported_policy_schema,
                ContentDigest(
                    self.evaluator_ref.implementation_build_digest.algorithm,
                    self.evaluator_ref.implementation_build_digest.hex_digest,
                ),
            ),
            rules=self.rules.validated(),
            author_actor_id=ActorId(self.author_actor_id.value),
            created_at_us=self.created_at_us,
            policy_digest=ContentDigest(
                self.policy_digest.algorithm, self.policy_digest.hex_digest
            ),
        )

    def rules_payload(self) -> dict[str, JsonValue]:
        return _policy_payload(
            self.semantic_label,
            self.policy_schema_version,
            self.policy_schema_code,
            self.evaluator_ref,
            self.rules,
            self.author_actor_id,
        )

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(self.release_policy_version_id, self.policy_digest)
