"""Sign-off-free release content bindings and nonrecursive candidate snapshots."""

from __future__ import annotations

from copy import copy
import unittest

from heritage_production.domain.release import (
    ReleaseCandidateSnapshot,
    ReleaseContentBinding,
    ReleaseMember,
)
from heritage_production.domain.review import FindingDecision
from heritage_production.domain.shared import (
    ContentDigest,
    ExternalGateSetId,
    ExternalGateSetRef,
    ManifestMemberRole,
    PolicyRef,
    ProductionId,
    ReleaseCandidateId,
    ReleaseCandidateRef,
    ReleaseContentManifestId,
    ReleaseContentManifestRef,
    ValidationError,
    semantic_digest,
)

from tests.heritage_production.heritage_release_fixtures import (
    artifact,
    closed_review,
    digest,
    edition_ref,
    policy_version_id,
    production_id,
    successor_edition_ref,
    uid,
)


GATE_SET_REF = ExternalGateSetRef(ExternalGateSetId(uid(30)), digest("8"))
POLICY_REF = PolicyRef(policy_version_id(), digest("9"))
MANIFEST_ID = ReleaseContentManifestId(uid(7))
CANDIDATE_ID = ReleaseCandidateId(uid(50))


def members() -> tuple[ReleaseMember, ...]:
    return (
        ReleaseMember(ManifestMemberRole("transcript-json"), artifact(80, "1")),
        ReleaseMember(
            ManifestMemberRole("transcript-markdown"), artifact(81, "2", "text/markdown")
        ),
    )


def seal_content(
    *,
    evidence: object | None = None,
    edition: object | None = None,
    policy_ref: PolicyRef = POLICY_REF,
    gate_set_ref: ExternalGateSetRef = GATE_SET_REF,
    owner: ProductionId | None = None,
    release_members: tuple[ReleaseMember, ...] | None = None,
) -> ReleaseContentBinding:
    review_evidence = evidence if evidence is not None else closed_review()
    return ReleaseContentBinding.seal(
        release_content_manifest_id=MANIFEST_ID,
        production_id=owner or production_id(),
        edition_ref=edition or edition_ref(),
        review_evidence=review_evidence,
        policy_ref=policy_ref,
        external_gate_set_ref=gate_set_ref,
        members=release_members if release_members is not None else members(),
        provenance_input_digests=(digest("a"), digest("b")),
        integrity_input_digests=(digest("c"),),
        wrapper_artifact=artifact(82, "3"),
    )


def seal_candidate(
    content: ReleaseContentBinding,
    *,
    sign_off_digests: tuple[ContentDigest, ...] = (),
    candidate_id: ReleaseCandidateId = CANDIDATE_ID,
) -> ReleaseCandidateSnapshot:
    return ReleaseCandidateSnapshot.seal(
        release_candidate_id=candidate_id,
        production_id=content.production_id,
        content_manifest_ref=content.content_manifest_ref,
        included_sign_off_digests=sign_off_digests,
        assembled_at_us=1_700_000_000_000_010,
    )


class ReleaseMemberTests(unittest.TestCase):
    def test_member_binds_a_semantic_role_and_exact_artifact(self) -> None:
        member = members()[0]

        self.assertEqual(member.member_role, ManifestMemberRole("transcript-json"))
        self.assertEqual(member.artifact, artifact(80, "1"))


class ReleaseContentBindingTests(unittest.TestCase):
    def test_seal_binds_the_exact_selection_graph(self) -> None:
        evidence = closed_review()
        content = seal_content(evidence=evidence)

        self.assertEqual(content.review_evidence_ref, evidence.evidence_ref)
        self.assertEqual(content.edition_ref, edition_ref())
        self.assertEqual(content.policy_ref, POLICY_REF)
        self.assertEqual(content.external_gate_set_ref, GATE_SET_REF)
        self.assertEqual(content, content.validated())

    def test_content_digest_matches_its_literal_documented_preimage(self) -> None:
        evidence = closed_review()
        content = seal_content(evidence=evidence)

        expected = semantic_digest(
            "heritage-release-content-v1",
            {
                "production_id": production_id().value,
                "edition_ref": {
                    "transcript_edition_id": edition_ref().transcript_edition_id.value,
                    "content_digest": {
                        "algorithm": "sha256",
                        "hex_digest": edition_ref().content_digest.hex_digest,
                    },
                },
                "review_evidence_ref": {
                    "review_round_id": evidence.evidence_ref.review_round_id.value,
                    "evidence_digest": {
                        "algorithm": "sha256",
                        "hex_digest": evidence.evidence_ref.evidence_digest.hex_digest,
                    },
                },
                "policy_ref": {
                    "release_policy_version_id": policy_version_id().value,
                    "policy_digest": {
                        "algorithm": "sha256",
                        "hex_digest": POLICY_REF.policy_digest.hex_digest,
                    },
                },
                "external_gate_set_ref": {
                    "external_gate_set_id": GATE_SET_REF.external_gate_set_id.value,
                    "content_digest": {
                        "algorithm": "sha256",
                        "hex_digest": GATE_SET_REF.content_digest.hex_digest,
                    },
                },
                "members": [
                    {
                        "member_role": "transcript-json",
                        "artifact": {
                            "artifact_id": artifact(80, "1").artifact_id.value,
                            "content_digest": {
                                "algorithm": "sha256",
                                "hex_digest": "1" * 64,
                            },
                            "byte_size": 128,
                            "media_type": "application/json",
                        },
                    },
                    {
                        "member_role": "transcript-markdown",
                        "artifact": {
                            "artifact_id": artifact(81, "2").artifact_id.value,
                            "content_digest": {
                                "algorithm": "sha256",
                                "hex_digest": "2" * 64,
                            },
                            "byte_size": 128,
                            "media_type": "text/markdown",
                        },
                    },
                ],
                "provenance_input_digests": [
                    {"algorithm": "sha256", "hex_digest": "a" * 64},
                    {"algorithm": "sha256", "hex_digest": "b" * 64},
                ],
                "integrity_input_digests": [
                    {"algorithm": "sha256", "hex_digest": "c" * 64}
                ],
            },
        )

        self.assertEqual(content.content_manifest_ref.semantic_digest, expected)

    def test_manifest_identity_and_wrapper_artifact_are_excluded(self) -> None:
        first = seal_content()
        second = ReleaseContentBinding.seal(
            release_content_manifest_id=ReleaseContentManifestId(uid(77)),
            production_id=production_id(),
            edition_ref=edition_ref(),
            review_evidence=closed_review(),
            policy_ref=POLICY_REF,
            external_gate_set_ref=GATE_SET_REF,
            members=members(),
            provenance_input_digests=(digest("a"), digest("b")),
            integrity_input_digests=(digest("c"),),
            wrapper_artifact=artifact(99, "e"),
        )

        self.assertNotEqual(
            first.content_manifest_ref.release_content_manifest_id,
            second.content_manifest_ref.release_content_manifest_id,
        )
        self.assertNotEqual(
            first.content_manifest_ref.artifact, second.content_manifest_ref.artifact
        )
        self.assertEqual(
            first.content_manifest_ref.semantic_digest,
            second.content_manifest_ref.semantic_digest,
        )

    def test_review_evidence_must_bind_the_same_edition(self) -> None:
        with self.assertRaises(ValidationError):
            seal_content(edition=successor_edition_ref())

    def test_review_evidence_must_belong_to_this_production(self) -> None:
        with self.assertRaises(ValidationError):
            seal_content(owner=ProductionId(uid(555)))

    def test_zero_submission_review_still_binds_its_exact_production(self) -> None:
        # Closed evidence names its own Production, so a round closed with no
        # finalized submission is checked exactly like a reviewed one.
        evidence = closed_review(with_submission=False)
        self.assertEqual(evidence.submission_summaries, ())
        self.assertEqual(evidence.production_id, production_id())

        with self.assertRaises(ValidationError):
            seal_content(evidence=evidence, owner=ProductionId(uid(555)))

    def test_members_must_be_canonical_and_unique_by_role(self) -> None:
        with self.assertRaises(ValidationError):
            seal_content(release_members=tuple(reversed(members())))
        with self.assertRaises(ValidationError):
            seal_content(release_members=(members()[0], members()[0]))

    def test_noncanonical_provenance_digests_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ReleaseContentBinding.seal(
                release_content_manifest_id=MANIFEST_ID,
                production_id=production_id(),
                edition_ref=edition_ref(),
                review_evidence=closed_review(),
                policy_ref=POLICY_REF,
                external_gate_set_ref=GATE_SET_REF,
                members=members(),
                provenance_input_digests=(digest("b"), digest("a")),
                integrity_input_digests=(),
                wrapper_artifact=artifact(82, "3"),
            )

    def test_reconstitute_rejects_a_stale_or_mismatched_binding(self) -> None:
        content = seal_content()

        restored = ReleaseContentBinding.reconstitute(
            content_manifest_ref=content.content_manifest_ref,
            production_id=content.production_id,
            edition_ref=content.edition_ref,
            review_evidence=content.review_evidence,
            policy_ref=content.policy_ref,
            external_gate_set_ref=content.external_gate_set_ref,
            members=content.members,
            provenance_input_digests=content.provenance_input_digests,
            integrity_input_digests=content.integrity_input_digests,
        )
        self.assertEqual(restored, content)

        with self.assertRaises(ValidationError):
            ReleaseContentBinding.reconstitute(
                content_manifest_ref=ReleaseContentManifestRef(
                    MANIFEST_ID, digest("f"), artifact(82, "3")
                ),
                production_id=content.production_id,
                edition_ref=content.edition_ref,
                review_evidence=content.review_evidence,
                policy_ref=content.policy_ref,
                external_gate_set_ref=content.external_gate_set_ref,
                members=content.members,
                provenance_input_digests=content.provenance_input_digests,
                integrity_input_digests=content.integrity_input_digests,
            )

    def test_sign_offs_and_candidate_identity_are_absent_from_content(self) -> None:
        content = seal_content()

        self.assertFalse(hasattr(content, "sign_offs"))
        self.assertFalse(hasattr(content, "release_candidate_id"))
        self.assertFalse(hasattr(content, "approval"))

    def test_member_role_lookup_reports_available_roles(self) -> None:
        content = seal_content()

        self.assertEqual(
            content.member_roles,
            (
                ManifestMemberRole("transcript-json"),
                ManifestMemberRole("transcript-markdown"),
            ),
        )
        self.assertEqual(
            content.member_digest(ManifestMemberRole("transcript-json")),
            artifact(80, "1").content_digest,
        )
        self.assertIsNone(content.member_digest(ManifestMemberRole("absent")))

    def test_content_binding_carries_the_evaluable_review_evidence(self) -> None:
        evidence = closed_review(finding_decision=FindingDecision.ACCEPTED)
        content = seal_content(evidence=evidence)

        self.assertEqual(len(content.review_evidence.findings), 1)
        self.assertIs(
            content.review_evidence.findings[0].disposition.decision,
            FindingDecision.ACCEPTED,
        )


class ReleaseCandidateSnapshotTests(unittest.TestCase):
    def test_candidate_may_retain_an_incomplete_sign_off_set(self) -> None:
        content = seal_content()

        candidate = seal_candidate(content)

        self.assertEqual(candidate.included_sign_off_digests, ())
        self.assertEqual(
            candidate.ref,
            ReleaseCandidateRef(candidate.release_candidate_id, candidate.semantic_digest),
        )

    def test_candidate_digest_matches_its_literal_documented_preimage(self) -> None:
        content = seal_content()
        candidate = seal_candidate(content, sign_off_digests=(digest("2"), digest("4")))

        expected = semantic_digest(
            "heritage-release-candidate-v1",
            {
                "production_id": production_id().value,
                "content_manifest_ref": {
                    "release_content_manifest_id": MANIFEST_ID.value,
                    "semantic_digest": {
                        "algorithm": "sha256",
                        "hex_digest": content.content_manifest_ref.semantic_digest.hex_digest,
                    },
                    "artifact": {
                        "artifact_id": artifact(82, "3").artifact_id.value,
                        "content_digest": {
                            "algorithm": "sha256",
                            "hex_digest": "3" * 64,
                        },
                        "byte_size": 128,
                        "media_type": "application/json",
                    },
                },
                "included_sign_off_digests": [
                    {"algorithm": "sha256", "hex_digest": "2" * 64},
                    {"algorithm": "sha256", "hex_digest": "4" * 64},
                ],
            },
        )

        self.assertEqual(candidate.semantic_digest, expected)

    def test_candidate_identity_and_assembly_time_are_excluded(self) -> None:
        content = seal_content()
        first = seal_candidate(content)
        second = ReleaseCandidateSnapshot.seal(
            release_candidate_id=ReleaseCandidateId(uid(51)),
            production_id=content.production_id,
            content_manifest_ref=content.content_manifest_ref,
            included_sign_off_digests=(),
            assembled_at_us=1_900_000_000_000_000,
        )

        self.assertNotEqual(first.release_candidate_id, second.release_candidate_id)
        self.assertEqual(first.semantic_digest, second.semantic_digest)

    def test_sign_off_digests_must_be_canonical_and_unique(self) -> None:
        content = seal_content()

        with self.assertRaises(ValidationError):
            seal_candidate(content, sign_off_digests=(digest("4"), digest("2")))
        with self.assertRaises(ValidationError):
            seal_candidate(content, sign_off_digests=(digest("2"), digest("2")))

    def test_changed_sign_off_set_produces_a_distinct_snapshot(self) -> None:
        content = seal_content()
        first = seal_candidate(content)
        second = seal_candidate(content, sign_off_digests=(digest("2"),))

        self.assertNotEqual(first.semantic_digest, second.semantic_digest)

    def test_candidate_digest_never_contains_itself(self) -> None:
        content = seal_content()
        candidate = seal_candidate(content, sign_off_digests=(digest("2"),))

        self.assertNotIn(
            candidate.semantic_digest.hex_digest,
            [value.hex_digest for value in candidate.included_sign_off_digests],
        )

    def test_reconstitute_rejects_a_tampered_candidate_digest(self) -> None:
        content = seal_content()
        candidate = seal_candidate(content)

        with self.assertRaises(ValidationError):
            ReleaseCandidateSnapshot.reconstitute(
                release_candidate_id=candidate.release_candidate_id,
                production_id=candidate.production_id,
                content_manifest_ref=candidate.content_manifest_ref,
                included_sign_off_digests=candidate.included_sign_off_digests,
                assembled_at_us=candidate.assembled_at_us,
                semantic_digest=digest("f"),
            )

        forged = copy(candidate)
        object.__setattr__(forged, "assembled_at_us", 1)
        self.assertEqual(forged.validated().semantic_digest, candidate.semantic_digest)

    def test_candidate_production_must_match_its_content_owner(self) -> None:
        content = seal_content()

        with self.assertRaises(ValidationError):
            ReleaseCandidateSnapshot.seal(
                release_candidate_id=CANDIDATE_ID,
                production_id=ProductionId(uid(555)),
                content_manifest_ref=content.content_manifest_ref,
                included_sign_off_digests=(),
                assembled_at_us=1,
            ).bind(content)


if __name__ == "__main__":
    unittest.main()
