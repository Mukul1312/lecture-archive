"""Sign-off-free release content bindings and nonrecursive candidate snapshots.

Assembly is deliberately two-stage: `ReleaseContentBinding` seals the exact
edition, review, policy, and gate-set graph without any sign-off, so external
actors can sign a digest that never contains itself. `ReleaseCandidateSnapshot`
then records that manifest reference together with the ordered sign-off digests.
"""

from __future__ import annotations

from dataclasses import dataclass

from heritage_production.domain.review import ClosedReviewEvidence
from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    EditionRef,
    ExternalGateSetId,
    ExternalGateSetRef,
    JsonValue,
    ManifestMemberRole,
    PolicyRef,
    ProductionId,
    ReleaseCandidateId,
    ReleaseCandidateRef,
    ReleaseContentManifestId,
    ReleaseContentManifestRef,
    ReleasePolicyVersionId,
    ReviewEvidenceRef,
    TranscriptEditionId,
    ValidationError,
    semantic_digest,
)


def _digest_value(value: ContentDigest) -> dict[str, JsonValue]:
    return {"algorithm": value.algorithm, "hex_digest": value.hex_digest}


def _artifact_value(value: ArtifactRef) -> dict[str, JsonValue]:
    return {
        "artifact_id": value.artifact_id.value,
        "content_digest": _digest_value(value.content_digest),
        "byte_size": value.byte_size,
        "media_type": value.media_type,
    }


def _require_exact(value: object, expected: type[object], field: str) -> None:
    if type(value) is not expected:
        raise ValidationError(f"{field} must be an exact {expected.__name__}")


def _require_canonical_digests(
    values: tuple[ContentDigest, ...], *, field: str
) -> None:
    if type(values) is not tuple or not all(
        type(value) is ContentDigest for value in values
    ):
        raise ValidationError(f"{field} must be an immutable tuple of ContentDigest")
    keys = tuple(value.hex_digest for value in values)
    if keys != tuple(sorted(keys)):
        raise ValidationError(f"{field} must already be in canonical digest order")
    if len(set(keys)) != len(keys):
        raise ValidationError(f"{field} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ReleaseMember:
    """One allowlisted release-package member identified by role and exact bytes."""

    member_role: ManifestMemberRole
    artifact: ArtifactRef

    def __post_init__(self) -> None:
        _require_exact(self.member_role, ManifestMemberRole, "member_role")
        _require_exact(self.artifact, ArtifactRef, "artifact")

    def validated(self) -> "ReleaseMember":
        """Reconstruct this member and its exact artifact."""
        try:
            return ReleaseMember(
                ManifestMemberRole(self.member_role.value),
                ArtifactRef(
                    ArtifactId(self.artifact.artifact_id.value),
                    ContentDigest(
                        self.artifact.content_digest.algorithm,
                        self.artifact.content_digest.hex_digest,
                    ),
                    self.artifact.byte_size,
                    self.artifact.media_type,
                ),
            )
        except AttributeError as error:
            raise ValidationError("release member is incomplete") from error

    def payload(self) -> dict[str, JsonValue]:
        return {
            "member_role": self.member_role.value,
            "artifact": _artifact_value(self.artifact),
        }


def _content_payload(
    production_id: ProductionId,
    edition_ref: EditionRef,
    review_evidence_ref: ReviewEvidenceRef,
    policy_ref: PolicyRef,
    external_gate_set_ref: ExternalGateSetRef,
    members: tuple[ReleaseMember, ...],
    provenance_input_digests: tuple[ContentDigest, ...],
    integrity_input_digests: tuple[ContentDigest, ...],
) -> dict[str, JsonValue]:
    return {
        "production_id": production_id.value,
        "edition_ref": {
            "transcript_edition_id": edition_ref.transcript_edition_id.value,
            "content_digest": _digest_value(edition_ref.content_digest),
        },
        "review_evidence_ref": {
            "review_round_id": review_evidence_ref.review_round_id.value,
            "evidence_digest": _digest_value(review_evidence_ref.evidence_digest),
        },
        "policy_ref": {
            "release_policy_version_id": policy_ref.release_policy_version_id.value,
            "policy_digest": _digest_value(policy_ref.policy_digest),
        },
        "external_gate_set_ref": {
            "external_gate_set_id": external_gate_set_ref.external_gate_set_id.value,
            "content_digest": _digest_value(external_gate_set_ref.content_digest),
        },
        "members": [value.payload() for value in members],
        "provenance_input_digests": [
            _digest_value(value) for value in provenance_input_digests
        ],
        "integrity_input_digests": [
            _digest_value(value) for value in integrity_input_digests
        ],
    }


@dataclass(frozen=True, slots=True)
class ReleaseContentBinding:
    """An immutable, sign-off-free projection of one exact release selection."""

    content_manifest_ref: ReleaseContentManifestRef
    production_id: ProductionId
    edition_ref: EditionRef
    review_evidence_ref: ReviewEvidenceRef
    review_evidence: ClosedReviewEvidence
    policy_ref: PolicyRef
    external_gate_set_ref: ExternalGateSetRef
    members: tuple[ReleaseMember, ...]
    provenance_input_digests: tuple[ContentDigest, ...]
    integrity_input_digests: tuple[ContentDigest, ...]

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            (
                "content_manifest_ref",
                self.content_manifest_ref,
                ReleaseContentManifestRef,
            ),
            ("production_id", self.production_id, ProductionId),
            ("edition_ref", self.edition_ref, EditionRef),
            ("review_evidence_ref", self.review_evidence_ref, ReviewEvidenceRef),
            ("review_evidence", self.review_evidence, ClosedReviewEvidence),
            ("policy_ref", self.policy_ref, PolicyRef),
            ("external_gate_set_ref", self.external_gate_set_ref, ExternalGateSetRef),
        ):
            _require_exact(value, expected, field_name)
        if type(self.members) is not tuple or not all(
            type(value) is ReleaseMember for value in self.members
        ):
            raise ValidationError("members must be an immutable tuple of ReleaseMember")
        roles = tuple(value.member_role.value for value in self.members)
        if roles != tuple(sorted(roles)):
            raise ValidationError("release members must already be in canonical role order")
        if len(set(roles)) != len(roles):
            raise ValidationError("release member roles must be unique")
        _require_canonical_digests(
            self.provenance_input_digests, field="provenance_input_digests"
        )
        _require_canonical_digests(
            self.integrity_input_digests, field="integrity_input_digests"
        )

        # The closed evidence recomputes its digest-bound graph from its own
        # stored target manifest and assignments. See
        # ClosedReviewEvidence.validated() for the reviewer trust fields that
        # design section 8.2 excludes from every preimage.
        checked_evidence = self.review_evidence.validated()
        if checked_evidence != self.review_evidence:
            raise ValidationError("closed review evidence failed reconstruction")
        if checked_evidence.evidence_ref != self.review_evidence_ref:
            raise ValidationError(
                "release content review-evidence ref is not its exact evidence snapshot"
            )
        if checked_evidence.edition_ref != self.edition_ref:
            raise ValidationError(
                "closed review evidence does not bind the selected edition"
            )
        if checked_evidence.target_manifest_ref.review_round_id != (
            self.review_evidence_ref.review_round_id
        ):
            raise ValidationError("closed review evidence names a foreign review round")
        # The evidence names its own Production, so this holds for a round closed
        # with zero submissions exactly as it does for a reviewed one.
        if checked_evidence.production_id != self.production_id:
            raise ValidationError(
                "closed review evidence was produced for a different Production"
            )
        if any(
            summary.production_id != self.production_id
            for summary in checked_evidence.submission_summaries
        ):
            raise ValidationError(
                "a finalized submission names a different Production"
            )

        expected_digest = semantic_digest(
            "heritage-release-content-v1",
            _content_payload(
                self.production_id,
                self.edition_ref,
                self.review_evidence_ref,
                self.policy_ref,
                self.external_gate_set_ref,
                self.members,
                self.provenance_input_digests,
                self.integrity_input_digests,
            ),
        )
        if expected_digest != self.content_manifest_ref.semantic_digest:
            raise ValidationError(
                "release-content digest does not match its sealed selection graph"
            )

    @classmethod
    def seal(
        cls,
        *,
        release_content_manifest_id: ReleaseContentManifestId,
        production_id: ProductionId,
        edition_ref: EditionRef,
        review_evidence: ClosedReviewEvidence,
        policy_ref: PolicyRef,
        external_gate_set_ref: ExternalGateSetRef,
        members: tuple[ReleaseMember, ...],
        provenance_input_digests: tuple[ContentDigest, ...],
        integrity_input_digests: tuple[ContentDigest, ...],
        wrapper_artifact: ArtifactRef,
    ) -> ReleaseContentBinding:
        _require_exact(review_evidence, ClosedReviewEvidence, "review_evidence")
        try:
            digest = semantic_digest(
                "heritage-release-content-v1",
                _content_payload(
                    production_id,
                    edition_ref,
                    review_evidence.evidence_ref,
                    policy_ref,
                    external_gate_set_ref,
                    members,
                    provenance_input_digests,
                    integrity_input_digests,
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed release-content semantic input") from error
        return cls(
            ReleaseContentManifestRef(
                release_content_manifest_id, digest, wrapper_artifact
            ),
            production_id,
            edition_ref,
            review_evidence.evidence_ref,
            review_evidence,
            policy_ref,
            external_gate_set_ref,
            members,
            provenance_input_digests,
            integrity_input_digests,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        content_manifest_ref: ReleaseContentManifestRef,
        production_id: ProductionId,
        edition_ref: EditionRef,
        review_evidence: ClosedReviewEvidence,
        policy_ref: PolicyRef,
        external_gate_set_ref: ExternalGateSetRef,
        members: tuple[ReleaseMember, ...],
        provenance_input_digests: tuple[ContentDigest, ...],
        integrity_input_digests: tuple[ContentDigest, ...],
    ) -> ReleaseContentBinding:
        _require_exact(review_evidence, ClosedReviewEvidence, "review_evidence")
        return cls(
            content_manifest_ref,
            production_id,
            edition_ref,
            review_evidence.evidence_ref,
            review_evidence,
            policy_ref,
            external_gate_set_ref,
            members,
            provenance_input_digests,
            integrity_input_digests,
        )

    def validated(self) -> ReleaseContentBinding:
        """Reconstruct this binding and every reachable child value."""
        manifest = self.content_manifest_ref
        try:
            manifest_ref = ReleaseContentManifestRef(
                ReleaseContentManifestId(manifest.release_content_manifest_id.value),
                ContentDigest(
                    manifest.semantic_digest.algorithm,
                    manifest.semantic_digest.hex_digest,
                ),
                ArtifactRef(
                    ArtifactId(manifest.artifact.artifact_id.value),
                    ContentDigest(
                        manifest.artifact.content_digest.algorithm,
                        manifest.artifact.content_digest.hex_digest,
                    ),
                    manifest.artifact.byte_size,
                    manifest.artifact.media_type,
                ),
            )
            edition_ref = EditionRef(
                TranscriptEditionId(self.edition_ref.transcript_edition_id.value),
                ContentDigest(
                    self.edition_ref.content_digest.algorithm,
                    self.edition_ref.content_digest.hex_digest,
                ),
            )
            policy_ref = PolicyRef(
                ReleasePolicyVersionId(
                    self.policy_ref.release_policy_version_id.value
                ),
                ContentDigest(
                    self.policy_ref.policy_digest.algorithm,
                    self.policy_ref.policy_digest.hex_digest,
                ),
            )
            gate_set_ref = ExternalGateSetRef(
                ExternalGateSetId(
                    self.external_gate_set_ref.external_gate_set_id.value
                ),
                ContentDigest(
                    self.external_gate_set_ref.content_digest.algorithm,
                    self.external_gate_set_ref.content_digest.hex_digest,
                ),
            )
            digest_groups = tuple(
                tuple(
                    ContentDigest(item.algorithm, item.hex_digest) for item in group
                )
                for group in (
                    self.provenance_input_digests,
                    self.integrity_input_digests,
                )
            )
        except AttributeError as error:
            raise ValidationError("release content binding is incomplete") from error
        return type(self).reconstitute(
            content_manifest_ref=manifest_ref,
            production_id=ProductionId(self.production_id.value),
            edition_ref=edition_ref,
            review_evidence=self.review_evidence,
            policy_ref=policy_ref,
            external_gate_set_ref=gate_set_ref,
            members=tuple(value.validated() for value in self.members),
            provenance_input_digests=digest_groups[0],
            integrity_input_digests=digest_groups[1],
        )

    @property
    def member_roles(self) -> tuple[ManifestMemberRole, ...]:
        return tuple(value.member_role for value in self.members)

    def member_digest(self, member_role: ManifestMemberRole) -> ContentDigest | None:
        _require_exact(member_role, ManifestMemberRole, "member_role")
        for value in self.members:
            if value.member_role == member_role:
                return value.artifact.content_digest
        return None

    @property
    def semantic_digest(self) -> ContentDigest:
        return self.content_manifest_ref.semantic_digest


def _candidate_payload(
    production_id: ProductionId,
    content_manifest_ref: ReleaseContentManifestRef,
    included_sign_off_digests: tuple[ContentDigest, ...],
) -> dict[str, JsonValue]:
    return {
        "production_id": production_id.value,
        "content_manifest_ref": {
            "release_content_manifest_id": (
                content_manifest_ref.release_content_manifest_id.value
            ),
            "semantic_digest": _digest_value(content_manifest_ref.semantic_digest),
            "artifact": _artifact_value(content_manifest_ref.artifact),
        },
        "included_sign_off_digests": [
            _digest_value(value) for value in included_sign_off_digests
        ],
    }


@dataclass(frozen=True, slots=True)
class ReleaseCandidateSnapshot:
    """An immutable, append-only Production-owned candidate record."""

    release_candidate_id: ReleaseCandidateId
    production_id: ProductionId
    content_manifest_ref: ReleaseContentManifestRef
    included_sign_off_digests: tuple[ContentDigest, ...]
    assembled_at_us: int
    semantic_digest: ContentDigest

    def __post_init__(self) -> None:
        for field_name, value, expected in (
            ("release_candidate_id", self.release_candidate_id, ReleaseCandidateId),
            ("production_id", self.production_id, ProductionId),
            (
                "content_manifest_ref",
                self.content_manifest_ref,
                ReleaseContentManifestRef,
            ),
            ("semantic_digest", self.semantic_digest, ContentDigest),
        ):
            _require_exact(value, expected, field_name)
        _require_canonical_digests(
            self.included_sign_off_digests, field="included_sign_off_digests"
        )
        if type(self.assembled_at_us) is not int or self.assembled_at_us <= 0:
            raise ValidationError("assembled_at_us must be a positive integer")

        expected_digest = semantic_digest(
            "heritage-release-candidate-v1",
            _candidate_payload(
                self.production_id,
                self.content_manifest_ref,
                self.included_sign_off_digests,
            ),
        )
        if expected_digest != self.semantic_digest:
            raise ValidationError("release-candidate digest does not match its snapshot")

    @classmethod
    def seal(
        cls,
        *,
        release_candidate_id: ReleaseCandidateId,
        production_id: ProductionId,
        content_manifest_ref: ReleaseContentManifestRef,
        included_sign_off_digests: tuple[ContentDigest, ...],
        assembled_at_us: int,
    ) -> ReleaseCandidateSnapshot:
        try:
            digest = semantic_digest(
                "heritage-release-candidate-v1",
                _candidate_payload(
                    production_id, content_manifest_ref, included_sign_off_digests
                ),
            )
        except (AttributeError, KeyError, TypeError) as error:
            raise ValidationError("malformed release-candidate semantic input") from error
        return cls(
            release_candidate_id,
            production_id,
            content_manifest_ref,
            included_sign_off_digests,
            assembled_at_us,
            digest,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        release_candidate_id: ReleaseCandidateId,
        production_id: ProductionId,
        content_manifest_ref: ReleaseContentManifestRef,
        included_sign_off_digests: tuple[ContentDigest, ...],
        assembled_at_us: int,
        semantic_digest: ContentDigest,
    ) -> ReleaseCandidateSnapshot:
        return cls(
            release_candidate_id,
            production_id,
            content_manifest_ref,
            included_sign_off_digests,
            assembled_at_us,
            semantic_digest,
        )

    def validated(self) -> ReleaseCandidateSnapshot:
        """Reconstruct this snapshot and every reachable child value."""
        manifest = self.content_manifest_ref
        try:
            manifest_ref = ReleaseContentManifestRef(
                ReleaseContentManifestId(manifest.release_content_manifest_id.value),
                ContentDigest(
                    manifest.semantic_digest.algorithm,
                    manifest.semantic_digest.hex_digest,
                ),
                ArtifactRef(
                    ArtifactId(manifest.artifact.artifact_id.value),
                    ContentDigest(
                        manifest.artifact.content_digest.algorithm,
                        manifest.artifact.content_digest.hex_digest,
                    ),
                    manifest.artifact.byte_size,
                    manifest.artifact.media_type,
                ),
            )
            digests = tuple(
                ContentDigest(value.algorithm, value.hex_digest)
                for value in self.included_sign_off_digests
            )
        except AttributeError as error:
            raise ValidationError("release candidate snapshot is incomplete") from error
        return type(self).reconstitute(
            release_candidate_id=ReleaseCandidateId(self.release_candidate_id.value),
            production_id=ProductionId(self.production_id.value),
            content_manifest_ref=manifest_ref,
            included_sign_off_digests=digests,
            assembled_at_us=self.assembled_at_us,
            semantic_digest=ContentDigest(
                self.semantic_digest.algorithm, self.semantic_digest.hex_digest
            ),
        )

    def bind(self, content: ReleaseContentBinding) -> ReleaseContentBinding:
        """Verify this snapshot names the supplied exact sign-off-free content."""
        _require_exact(content, ReleaseContentBinding, "content")
        if content.production_id != self.production_id:
            raise ValidationError("candidate and release content name different Productions")
        if content.content_manifest_ref != self.content_manifest_ref:
            raise ValidationError("candidate does not reference this exact release content")
        return content

    @property
    def ref(self) -> ReleaseCandidateRef:
        return ReleaseCandidateRef(self.release_candidate_id, self.semantic_digest)
