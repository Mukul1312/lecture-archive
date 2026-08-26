from __future__ import annotations

from dataclasses import replace
import unittest

try:
    from heritage_production.domain.review import (
        FindingCategoryCode,
        FindingSeverityCode,
        ReviewTargetAssetRef,
        ReviewTargetKey,
        ReviewTargetManifest,
        ReviewTargetMember,
        SemanticAssetRole,
    )
except ImportError:
    FindingCategoryCode = None  # type: ignore[assignment,misc]
    FindingSeverityCode = None  # type: ignore[assignment,misc]
    ReviewTargetAssetRef = None  # type: ignore[assignment,misc]
    ReviewTargetKey = None  # type: ignore[assignment,misc]
    ReviewTargetManifest = None  # type: ignore[assignment,misc]
    ReviewTargetMember = None  # type: ignore[assignment,misc]
    SemanticAssetRole = None  # type: ignore[assignment,misc]

from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    EditionRef,
    ProductionId,
    ReviewRoundId,
    RubricId,
    RubricRef,
    SegmentId,
    SegmentRevisionId,
    SegmentRevisionRef,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptEditionId,
    TranscriptText,
    ValidationError,
)


def uid(suffix: int) -> str:
    return f"123e4567-e89b-42d3-a456-{suffix:012x}"


def digest(character: str) -> ContentDigest:
    return ContentDigest("sha256", character * 64)


class ReviewTargetManifestTests(unittest.TestCase):
    def test_seal_binds_complete_typed_target_and_excludes_outer_artifact(self) -> None:
        self.assertIsNotNone(
            ReviewTargetManifest,
            "the Review target-manifest contract must exist",
        )

        source = SourceVersionRef(
            SourceVersionId(uid(1)),
            SourceRecordingId(uid(2)),
            digest("1"),
            20_000,
            "integer microseconds",
        )
        member = ReviewTargetMember(
            ordinal=0,
            target_key=ReviewTargetKey("segment:001"),
            segment_revision_ref=SegmentRevisionRef(
                SegmentId(uid(3)), SegmentRevisionId(uid(4)), digest("2")
            ),
            source_span=SourceSpan(source, 1_000, 3_000),
            transcript_text=TranscriptText("Namaste"),
            allowed_category_codes=(FindingCategoryCode("accuracy"),),
            allowed_severity_codes=(FindingSeverityCode("major"),),
            derived_audio=(
                ReviewTargetAssetRef(
                    SemanticAssetRole("review-audio"),
                    ArtifactRef(
                        ArtifactId(uid(5)), digest("3"), 321, "audio/flac"
                    ),
                ),
            ),
        )
        values = {
            "review_round_id": ReviewRoundId(uid(6)),
            "production_id": ProductionId(uid(7)),
            "edition_ref": EditionRef(TranscriptEditionId(uid(8)), digest("4")),
            "rubric_ref": RubricRef(RubricId(uid(9)), 2, digest("5")),
            "members": (member,),
        }
        first_artifact = ArtifactRef(
            ArtifactId(uid(10)), digest("6"), 1_024, "application/json"
        )
        second_artifact = ArtifactRef(
            ArtifactId(uid(11)), digest("7"), 2_048, "application/json"
        )

        first = ReviewTargetManifest.seal(artifact=first_artifact, **values)
        second = ReviewTargetManifest.seal(artifact=second_artifact, **values)

        self.assertEqual(
            first.semantic_digest.hex_digest,
            "fe654aa5a99bf2849be221ded43a7a4f61da3838de7951e4dde0fe325fe54989",
        )
        self.assertEqual(first.semantic_digest, second.semantic_digest)
        self.assertNotEqual(first.ref.artifact, second.ref.artifact)
        self.assertEqual(first.members, (member,))

    def test_opaque_values_and_member_collections_are_exact_and_canonical(self) -> None:
        for value_type in (
            ReviewTargetKey,
            FindingCategoryCode,
            FindingSeverityCode,
            SemanticAssetRole,
        ):
            with self.subTest(value_type=value_type):
                for invalid in ("", "e\u0301", "line\rbreak"):
                    with self.assertRaises(ValidationError):
                        value_type(invalid)
                with self.assertRaises(ValidationError):
                    value_type(1)  # type: ignore[arg-type]

        source = SourceVersionRef(
            SourceVersionId(uid(20)),
            SourceRecordingId(uid(21)),
            digest("1"),
            10_000,
            "integer microseconds",
        )
        revision = SegmentRevisionRef(
            SegmentId(uid(22)), SegmentRevisionId(uid(23)), digest("2")
        )
        asset = ReviewTargetAssetRef(
            SemanticAssetRole("audio"),
            ArtifactRef(ArtifactId(uid(24)), digest("3"), 1, "audio/flac"),
        )
        valid = {
            "ordinal": 0,
            "target_key": ReviewTargetKey("target"),
            "segment_revision_ref": revision,
            "source_span": SourceSpan(source, 0, 1_000),
            "transcript_text": TranscriptText("text"),
            "allowed_category_codes": (FindingCategoryCode("accuracy"),),
            "allowed_severity_codes": (FindingSeverityCode("major"),),
            "derived_audio": (asset,),
        }
        invalid_overrides = (
            {"ordinal": True},
            {"ordinal": -1},
            {"allowed_category_codes": [FindingCategoryCode("accuracy")]},
            {"allowed_category_codes": (FindingCategoryCode("accuracy"),) * 2},
            {"allowed_severity_codes": ()},
            {"derived_audio": (asset, asset)},
        )
        for override in invalid_overrides:
            with self.subTest(override=override):
                with self.assertRaises(ValidationError):
                    ReviewTargetMember(**(valid | override))

    def test_manifest_reconstitution_rejects_binding_order_and_membership_tampering(self) -> None:
        self.assertTrue(
            hasattr(ReviewTargetManifest, "reconstitute"),
            "stored target snapshots require a validating reconstitution path",
        )
        source = SourceVersionRef(
            SourceVersionId(uid(30)),
            SourceRecordingId(uid(31)),
            digest("1"),
            10_000,
            "integer microseconds",
        )

        def member(ordinal: int, suffix: int) -> ReviewTargetMember:
            return ReviewTargetMember(
                ordinal=ordinal,
                target_key=ReviewTargetKey(f"target-{suffix}"),
                segment_revision_ref=SegmentRevisionRef(
                    SegmentId(uid(40 + suffix)),
                    SegmentRevisionId(uid(50 + suffix)),
                    digest("2"),
                ),
                source_span=SourceSpan(source, suffix * 1_000, (suffix + 1) * 1_000),
                transcript_text=TranscriptText("text"),
                allowed_category_codes=(FindingCategoryCode("accuracy"),),
                allowed_severity_codes=(FindingSeverityCode("major"),),
            )

        first, second = member(0, 0), member(1, 1)
        manifest = ReviewTargetManifest.seal(
            review_round_id=ReviewRoundId(uid(60)),
            production_id=ProductionId(uid(61)),
            edition_ref=EditionRef(TranscriptEditionId(uid(62)), digest("3")),
            rubric_ref=RubricRef(RubricId(uid(63)), 1, digest("4")),
            members=(first, second),
            artifact=ArtifactRef(
                ArtifactId(uid(64)), digest("5"), 10, "application/json"
            ),
        )
        rebuilt = ReviewTargetManifest.reconstitute(
            ref=manifest.ref,
            production_id=manifest.production_id,
            edition_ref=manifest.edition_ref,
            rubric_ref=manifest.rubric_ref,
            members=manifest.members,
        )
        self.assertEqual(rebuilt, manifest)

        invalid_members = (
            (replace(first, ordinal=1), second),
            (first, replace(second, target_key=first.target_key)),
            (
                first,
                replace(second, segment_revision_ref=first.segment_revision_ref),
            ),
        )
        for members in invalid_members:
            with self.subTest(members=members):
                with self.assertRaises(ValidationError):
                    ReviewTargetManifest.reconstitute(
                        ref=manifest.ref,
                        production_id=manifest.production_id,
                        edition_ref=manifest.edition_ref,
                        rubric_ref=manifest.rubric_ref,
                        members=members,
                    )

        with self.assertRaises(ValidationError):
            ReviewTargetManifest.reconstitute(
                ref=replace(manifest.ref, review_round_id=ReviewRoundId(uid(65))),
                production_id=manifest.production_id,
                edition_ref=manifest.edition_ref,
                rubric_ref=manifest.rubric_ref,
                members=manifest.members,
            )


if __name__ == "__main__":
    unittest.main()
