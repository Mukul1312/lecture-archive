"""Sealed ReleasePolicyVersion normalization, ordering, and digest behavior."""

from __future__ import annotations

from copy import copy
import unittest

from heritage_production.domain.release import (
    SUPPORTED_EVALUATOR_REF,
    BlockingFindingRule,
    IntegrityCheckCode,
    ReleasePolicyRules,
    ReleasePolicyVersion,
    ReviewCoverageRequirement,
    SignOffRequirement,
    UncertaintyAllowance,
    UncertaintyLimitMetric,
)
from heritage_production.domain.review import FindingCategoryCode, FindingSeverityCode
from heritage_production.domain.shared import (
    AssuranceLevel,
    ContentDigest,
    GateScope,
    ManifestMemberRole,
    PolicyEvaluatorRef,
    PolicyRef,
    RoleCode,
    SignOffTargetKind,
    ValidationError,
    canonical_json,
    semantic_digest,
)
from heritage_production.domain.transcription import UncertaintyKind

from tests.heritage_production.heritage_release_fixtures import (
    actor,
    digest,
    policy_version_id,
)


# The single evaluator this build ships; a policy pinning any other build
# cannot be loaded (design 13.2), so tests bind the real one.
EVALUATOR = SUPPORTED_EVALUATOR_REF


def empty_rules() -> ReleasePolicyRules:
    return ReleasePolicyRules(
        required_integrity_checks=(),
        uncertainty_allowances=(),
        blocking_finding_rules=(),
        review_coverage_requirements=(),
        review_signoff_requirements=(),
        external_signoff_requirements=(),
        required_release_members=(),
        maximum_unresolved_findings=0,
    )


def configured_rules() -> ReleasePolicyRules:
    return ReleasePolicyRules(
        required_integrity_checks=(
            IntegrityCheckCode("object-digests"),
            IntegrityCheckCode("sealed-manifests"),
        ),
        uncertainty_allowances=(
            UncertaintyAllowance(
                UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, 3
            ),
            UncertaintyAllowance(
                UncertaintyKind.UNCERTAIN_WORDING,
                UncertaintyLimitMetric.SOURCE_DURATION_US,
                5_000_000,
            ),
        ),
        blocking_finding_rules=(
            BlockingFindingRule(
                FindingCategoryCode("accuracy"),
                (FindingSeverityCode("critical"), FindingSeverityCode("major")),
            ),
        ),
        review_coverage_requirements=(
            ReviewCoverageRequirement(RoleCode("language-reviewer"), 10_000, True),
        ),
        review_signoff_requirements=(
            SignOffRequirement(
                GateScope.REVIEW,
                RoleCode("language-reviewer"),
                SignOffTargetKind.REVIEW_TARGET,
                None,
                AssuranceLevel.STEWARD_ATTESTED,
                1,
            ),
        ),
        external_signoff_requirements=(
            SignOffRequirement(
                GateScope.EXTERNAL_RELEASE,
                RoleCode("rights-holder"),
                SignOffTargetKind.RELEASE_CONTENT,
                None,
                AssuranceLevel.VERIFIED_SIGNATURE,
                1,
            ),
        ),
        required_release_members=(
            ManifestMemberRole("transcript-json"),
            ManifestMemberRole("transcript-markdown"),
        ),
        maximum_unresolved_findings=0,
    )


def seal_policy(rules: ReleasePolicyRules | None = None) -> ReleasePolicyVersion:
    return ReleasePolicyVersion.seal(
        release_policy_version_id=policy_version_id(),
        semantic_label="pilot-transcript-policy",
        policy_schema_version=1,
        policy_schema_code="heritage-transcript-policy-v1",
        evaluator_ref=EVALUATOR,
        rules=rules if rules is not None else configured_rules(),
        author_actor_id=actor(20),
        created_at_us=1_700_000_000_000_000,
    )


class ReleasePolicyRuleNormalizationTests(unittest.TestCase):
    def test_empty_rule_set_is_an_explicit_complete_value(self) -> None:
        rules = empty_rules()

        self.assertEqual(rules.required_integrity_checks, ())
        self.assertEqual(rules.maximum_unresolved_findings, 0)

    def test_every_rule_field_is_required(self) -> None:
        with self.assertRaises(TypeError):
            ReleasePolicyRules(required_integrity_checks=())  # type: ignore[call-arg]

    def test_noncanonical_rule_order_is_rejected_at_the_constructor(self) -> None:
        with self.assertRaises(ValidationError):
            ReleasePolicyRules(
                required_integrity_checks=(
                    IntegrityCheckCode("sealed-manifests"),
                    IntegrityCheckCode("object-digests"),
                ),
                uncertainty_allowances=(),
                blocking_finding_rules=(),
                review_coverage_requirements=(),
                review_signoff_requirements=(),
                external_signoff_requirements=(),
                required_release_members=(),
                maximum_unresolved_findings=0,
            )

    def test_duplicate_semantic_rule_keys_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ReleasePolicyRules(
                required_integrity_checks=(),
                uncertainty_allowances=(
                    UncertaintyAllowance(
                        UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, 1
                    ),
                    UncertaintyAllowance(
                        UncertaintyKind.INAUDIBLE,
                        UncertaintyLimitMetric.CHARACTER_COUNT,
                        2,
                    ),
                ),
                blocking_finding_rules=(),
                review_coverage_requirements=(),
                review_signoff_requirements=(),
                external_signoff_requirements=(),
                required_release_members=(),
                maximum_unresolved_findings=0,
            )

    def test_coverage_basis_points_are_bounded_inclusively(self) -> None:
        for basis_points in (0, 10_000):
            with self.subTest(basis_points=basis_points):
                ReviewCoverageRequirement(RoleCode("r"), basis_points, False)
        for basis_points in (-1, 10_001):
            with self.subTest(basis_points=basis_points):
                with self.assertRaises(ValidationError):
                    ReviewCoverageRequirement(RoleCode("r"), basis_points, False)

    def test_uncertainty_maximum_must_be_a_nonnegative_integer(self) -> None:
        UncertaintyAllowance(
            UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, 0
        )
        with self.assertRaises(ValidationError):
            UncertaintyAllowance(
                UncertaintyKind.INAUDIBLE, UncertaintyLimitMetric.MARK_COUNT, -1
            )

    def test_blocking_rule_requires_a_nonempty_canonical_severity_set(self) -> None:
        with self.assertRaises(ValidationError):
            BlockingFindingRule(FindingCategoryCode("accuracy"), ())
        with self.assertRaises(ValidationError):
            BlockingFindingRule(
                FindingCategoryCode("accuracy"),
                (FindingSeverityCode("major"), FindingSeverityCode("critical")),
            )

    def test_signoff_requirement_scope_and_target_must_agree(self) -> None:
        with self.assertRaises(ValidationError):
            SignOffRequirement(
                GateScope.REVIEW,
                RoleCode("r"),
                SignOffTargetKind.RELEASE_CONTENT,
                None,
                AssuranceLevel.STEWARD_ATTESTED,
                1,
            )
        with self.assertRaises(ValidationError):
            SignOffRequirement(
                GateScope.EXTERNAL_RELEASE,
                RoleCode("r"),
                SignOffTargetKind.REVIEW_TARGET,
                None,
                AssuranceLevel.STEWARD_ATTESTED,
                1,
            )

    def test_manifest_member_target_requires_its_member_role(self) -> None:
        with self.assertRaises(ValidationError):
            SignOffRequirement(
                GateScope.EXTERNAL_RELEASE,
                RoleCode("r"),
                SignOffTargetKind.MANIFEST_MEMBER,
                None,
                AssuranceLevel.VERIFIED_SIGNATURE,
                1,
            )
        with self.assertRaises(ValidationError):
            SignOffRequirement(
                GateScope.EXTERNAL_RELEASE,
                RoleCode("r"),
                SignOffTargetKind.RELEASE_CONTENT,
                ManifestMemberRole("transcript-json"),
                AssuranceLevel.VERIFIED_SIGNATURE,
                1,
            )

    def test_requirements_reject_unverified_minimum_and_nonpositive_count(self) -> None:
        with self.assertRaises(ValidationError):
            SignOffRequirement(
                GateScope.REVIEW,
                RoleCode("r"),
                SignOffTargetKind.REVIEW_TARGET,
                None,
                AssuranceLevel.UNVERIFIED,
                1,
            )
        with self.assertRaises(ValidationError):
            SignOffRequirement(
                GateScope.REVIEW,
                RoleCode("r"),
                SignOffTargetKind.REVIEW_TARGET,
                None,
                AssuranceLevel.STEWARD_ATTESTED,
                0,
            )


class ReleasePolicyVersionSealTests(unittest.TestCase):
    def test_seal_binds_a_stable_ref_and_recomputable_digest(self) -> None:
        policy = seal_policy()

        self.assertEqual(
            policy.ref, PolicyRef(policy.release_policy_version_id, policy.policy_digest)
        )
        self.assertEqual(policy, policy.validated())

    def test_policy_digest_matches_its_literal_documented_preimage(self) -> None:
        policy = seal_policy(empty_rules())

        expected = semantic_digest(
            "heritage-release-policy-v1",
            {
                "semantic_label": "pilot-transcript-policy",
                "policy_schema_version": 1,
                "policy_schema_code": "heritage-transcript-policy-v1",
                "evaluator_ref": {
                    "evaluator_name": EVALUATOR.evaluator_name,
                    "semantic_version": EVALUATOR.semantic_version,
                    "supported_policy_schema": EVALUATOR.supported_policy_schema,
                    "implementation_build_digest": {
                        "algorithm": "sha256",
                        "hex_digest": (
                            EVALUATOR.implementation_build_digest.hex_digest
                        ),
                    },
                },
                "rules": {
                    "required_integrity_checks": [],
                    "uncertainty_allowances": [],
                    "blocking_finding_rules": [],
                    "review_coverage_requirements": [],
                    "review_signoff_requirements": [],
                    "external_signoff_requirements": [],
                    "required_release_members": [],
                    "maximum_unresolved_findings": 0,
                },
                "author_actor_id": actor(20).value,
            },
        )

        self.assertEqual(policy.policy_digest, expected)

    def test_policy_identity_time_and_digest_are_excluded_from_the_preimage(self) -> None:
        first = seal_policy()
        second = ReleasePolicyVersion.seal(
            release_policy_version_id=policy_version_id(),
            semantic_label="pilot-transcript-policy",
            policy_schema_version=1,
            policy_schema_code="heritage-transcript-policy-v1",
            evaluator_ref=EVALUATOR,
            rules=configured_rules(),
            author_actor_id=actor(20),
            created_at_us=1_900_000_000_000_000,
        )

        self.assertNotEqual(first.created_at_us, second.created_at_us)
        self.assertEqual(first.policy_digest, second.policy_digest)

    def test_schema_code_must_match_the_pinned_evaluator(self) -> None:
        with self.assertRaises(ValidationError):
            ReleasePolicyVersion.seal(
                release_policy_version_id=policy_version_id(),
                semantic_label="pilot-transcript-policy",
                policy_schema_version=1,
                policy_schema_code="other-policy-schema",
                evaluator_ref=EVALUATOR,
                rules=empty_rules(),
                author_actor_id=actor(20),
                created_at_us=1,
            )

    def test_schema_version_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            ReleasePolicyVersion.seal(
                release_policy_version_id=policy_version_id(),
                semantic_label="pilot-transcript-policy",
                policy_schema_version=0,
                policy_schema_code="heritage-transcript-policy-v1",
                evaluator_ref=EVALUATOR,
                rules=empty_rules(),
                author_actor_id=actor(20),
                created_at_us=1,
            )

    def test_sealed_policy_is_immutable(self) -> None:
        policy = seal_policy()

        with self.assertRaises(Exception):
            policy.semantic_label = "changed"  # type: ignore[misc]


class ReleasePolicyVersionReconstituteTests(unittest.TestCase):
    def test_reconstitute_requires_the_exact_supplied_digest(self) -> None:
        policy = seal_policy()

        restored = ReleasePolicyVersion.reconstitute(
            release_policy_version_id=policy.release_policy_version_id,
            semantic_label=policy.semantic_label,
            policy_schema_version=policy.policy_schema_version,
            policy_schema_code=policy.policy_schema_code,
            evaluator_ref=policy.evaluator_ref,
            rules=policy.rules,
            author_actor_id=policy.author_actor_id,
            created_at_us=policy.created_at_us,
            policy_digest=policy.policy_digest,
        )

        self.assertEqual(restored, policy)

    def test_reconstitute_rejects_a_tampered_digest(self) -> None:
        policy = seal_policy()

        with self.assertRaises(ValidationError):
            ReleasePolicyVersion.reconstitute(
                release_policy_version_id=policy.release_policy_version_id,
                semantic_label=policy.semantic_label,
                policy_schema_version=policy.policy_schema_version,
                policy_schema_code=policy.policy_schema_code,
                evaluator_ref=policy.evaluator_ref,
                rules=policy.rules,
                author_actor_id=policy.author_actor_id,
                created_at_us=policy.created_at_us,
                policy_digest=digest("f"),
            )

    def test_validated_rejects_tampered_rules_behind_a_retained_digest(self) -> None:
        policy = seal_policy()
        forged = copy(policy)
        object.__setattr__(forged, "semantic_label", "forged-label")

        with self.assertRaises(ValidationError):
            forged.validated()

    def test_reconstitution_emits_no_events(self) -> None:
        policy = seal_policy()

        self.assertFalse(hasattr(policy, "pull_events"))


class ReleasePolicyCanonicalEncodingTests(unittest.TestCase):
    def test_rule_payload_is_canonical_json_encodable(self) -> None:
        policy = seal_policy()

        encoded = canonical_json(policy.rules_payload())

        self.assertIsInstance(encoded, bytes)
        self.assertEqual(canonical_json(policy.rules_payload()), encoded)


if __name__ == "__main__":
    unittest.main()
