from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from heritage_production.domain.shared import (
    ArtifactId,
    ArtifactRef,
    ContentDigest,
    ProposalItemId,
    ProposalSetId,
    ActorId,
    SourceRecordingId,
    SourceSpan,
    SourceVersionId,
    SourceVersionRef,
    TranscriptText,
    ValidationError,
)
from heritage_production.domain.transcription import (
    ASRProposalSet,
    ConfigurationEvidence,
    ConfidenceEvidence,
    EvidenceStatus,
    IdentityEvidence,
    ProposalItem,
    ProvenanceStatus,
    RawRowLocator,
    StewardAttestation,
)


def uid(suffix: int) -> str:
    return f"123e4567-e89b-42d3-a456-{suffix:012d}"


DIGEST_A = ContentDigest("sha256", "a" * 64)
DIGEST_B = ContentDigest("sha256", "b" * 64)
SOURCE = SourceVersionRef(
    SourceVersionId(uid(1)),
    SourceRecordingId(uid(2)),
    DIGEST_A,
    10_000,
    "microseconds",
)
RAW_ARTIFACT = ArtifactRef(ArtifactId(uid(3)), DIGEST_B, 512, "application/json")


def proposal_item(identifier: int = 10) -> ProposalItem:
    return ProposalItem(
        proposal_item_id=ProposalItemId(uid(identifier)),
        source_span=SourceSpan(SOURCE, 0, 10_000),
        proposed_text=TranscriptText("Namaste"),
        language="sa",
        speaker_hypothesis="speaker-1",
        confidence_evidence=(ConfidenceEvidence("posterior", "0.98"),),
        raw_row_locator=RawRowLocator("segments.jsonl#row=1"),
    )


def proposal_values(*, identifier: int = 20, imported_at_us: int = 100) -> dict[str, object]:
    return dict(
        proposal_set_id=ProposalSetId(uid(identifier)),
        source_version=SOURCE,
        package_schema_version=1,
        package_digest=DIGEST_A,
        importing_adapter="whisper-package",
        importing_adapter_version="1.0.0",
        tool_identity=IdentityEvidence(EvidenceStatus.VERIFIED, "whisper.cpp"),
        model_name=IdentityEvidence(EvidenceStatus.VERIFIED, "large-v3"),
        model_revision=IdentityEvidence(EvidenceStatus.VERIFIED, "model-sha-1"),
        configuration=ConfigurationEvidence(EvidenceStatus.VERIFIED, DIGEST_B),
        provenance_status=ProvenanceStatus.COMPLETE,
        missing_field_warnings=(),
        steward_attestation=None,
        imported_at_us=imported_at_us,
        raw_artifact=RAW_ARTIFACT,
        items=(proposal_item(),),
    )


def complete_proposal_set(
    *, identifier: int = 20, imported_at_us: int = 100, **overrides: object
) -> ASRProposalSet:
    values = proposal_values(identifier=identifier, imported_at_us=imported_at_us)
    values.update(overrides)
    return ASRProposalSet.create(**values)  # type: ignore[arg-type]


class ASRProposalSetCreationTests(unittest.TestCase):
    def test_complete_set_is_sealed_and_exposes_an_exact_semantic_reference(self) -> None:
        proposal_set = complete_proposal_set()

        self.assertEqual(proposal_set.source_version, SOURCE)
        self.assertEqual(proposal_set.items, (proposal_item(),))
        self.assertEqual(proposal_set.ref.proposal_set_id, ProposalSetId(uid(20)))
        self.assertEqual(proposal_set.ref.content_digest, proposal_set.semantic_digest)

    def test_complete_provenance_requires_verified_tool_model_and_configuration(self) -> None:
        cases = (
            {"tool_identity": IdentityEvidence(EvidenceStatus.OBSERVED, "whisper.cpp")},
            {"model_name": IdentityEvidence(EvidenceStatus.UNKNOWN, None)},
            {"model_revision": IdentityEvidence(EvidenceStatus.UNKNOWN, None)},
            {"configuration": ConfigurationEvidence(EvidenceStatus.UNKNOWN, None)},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(ValidationError):
                    complete_proposal_set(**override)

        observed_name = complete_proposal_set(
            model_name=IdentityEvidence(EvidenceStatus.OBSERVED, "large-v3")
        )
        self.assertEqual(observed_name.model_name.status, EvidenceStatus.OBSERVED)

    def test_legacy_attested_preserves_unknowns_warnings_and_steward_evidence(self) -> None:
        attestation = StewardAttestation(
            ActorId(uid(30)),
            "Legacy export predates model pinning",
            90,
            DIGEST_A,
        )
        proposal_set = complete_proposal_set(
            provenance_status=ProvenanceStatus.LEGACY_ATTESTED,
            tool_identity=IdentityEvidence(EvidenceStatus.OBSERVED, "legacy-whisper"),
            model_name=IdentityEvidence(EvidenceStatus.UNKNOWN, None),
            model_revision=IdentityEvidence(EvidenceStatus.UNKNOWN, None),
            configuration=ConfigurationEvidence(EvidenceStatus.UNKNOWN, None),
            missing_field_warnings=("model name, revision, and configuration unavailable",),
            steward_attestation=attestation,
        )

        self.assertEqual(proposal_set.steward_attestation, attestation)
        self.assertEqual(proposal_set.model_revision.status, EvidenceStatus.UNKNOWN)

    def test_legacy_attested_rejects_missing_warning_or_attestation(self) -> None:
        attestation = StewardAttestation(ActorId(uid(30)), "Legacy evidence", 90, DIGEST_A)
        base = {
            "provenance_status": ProvenanceStatus.LEGACY_ATTESTED,
            "model_revision": IdentityEvidence(EvidenceStatus.UNKNOWN, None),
            "configuration": ConfigurationEvidence(EvidenceStatus.UNKNOWN, None),
            "missing_field_warnings": ("model revision unavailable",),
            "steward_attestation": attestation,
        }
        for override in (
            {"missing_field_warnings": ()},
            {"steward_attestation": None},
        ):
            with self.subTest(override=override):
                values = base | override
                with self.assertRaises(ValidationError):
                    complete_proposal_set(**values)

    def test_items_require_exact_source_nonempty_order_and_unique_identities(self) -> None:
        conflicting_source = replace(SOURCE, artifact_digest=ContentDigest("sha256", "c" * 64))
        conflicting_item = replace(
            proposal_item(), source_span=SourceSpan(conflicting_source, 0, 10_000)
        )
        duplicate = replace(proposal_item(), proposed_text=TranscriptText("Different"))
        for items in ((), (conflicting_item,), (proposal_item(), duplicate)):
            with self.subTest(items=items):
                with self.assertRaises(ValidationError):
                    complete_proposal_set(items=items)

        with self.assertRaises(ValidationError):
            complete_proposal_set(source_version="audio.wav", items=(proposal_item(),))

    def test_unknown_evidence_is_explicit_and_rejects_claimed_values(self) -> None:
        with self.assertRaises(ValidationError):
            IdentityEvidence(EvidenceStatus.UNKNOWN, "maybe-whisper")
        with self.assertRaises(ValidationError):
            ConfigurationEvidence(EvidenceStatus.UNKNOWN, DIGEST_A)

    def test_digest_excludes_root_identity_and_import_time_but_includes_semantic_content(self) -> None:
        baseline = complete_proposal_set(identifier=20, imported_at_us=100)
        changed_identity_and_time = complete_proposal_set(identifier=21, imported_at_us=101)
        changed_content = complete_proposal_set(importing_adapter_version="1.0.1")

        self.assertEqual(baseline.semantic_digest, changed_identity_and_time.semantic_digest)
        self.assertNotEqual(baseline.semantic_digest, changed_content.semantic_digest)

    def test_digest_excludes_raw_artifact_identity_but_includes_its_byte_digest(self) -> None:
        baseline = complete_proposal_set()
        identity_only = complete_proposal_set(
            raw_artifact=replace(RAW_ARTIFACT, artifact_id=ArtifactId(uid(40)))
        )
        different_bytes = complete_proposal_set(
            raw_artifact=replace(
                RAW_ARTIFACT,
                content_digest=ContentDigest("sha256", "d" * 64),
            )
        )

        self.assertEqual(baseline.semantic_digest, identity_only.semantic_digest)
        self.assertNotEqual(baseline.semantic_digest, different_bytes.semantic_digest)

    def test_raw_row_locator_separates_stable_member_from_observed_absolute_path(self) -> None:
        baseline_locator = RawRowLocator(
            "segments.jsonl#row=1",
            r"C:\imports\first\segments.jsonl",
        )
        relocated_locator = RawRowLocator(
            "segments.jsonl#row=1",
            "/mnt/archive/second/segments.jsonl",
        )
        changed_row_locator = RawRowLocator(
            "segments.jsonl#row=2",
            r"C:\imports\first\segments.jsonl",
        )
        baseline = complete_proposal_set(
            items=(replace(proposal_item(), raw_row_locator=baseline_locator),)
        )
        relocated = complete_proposal_set(
            items=(replace(proposal_item(), raw_row_locator=relocated_locator),)
        )
        changed_row = complete_proposal_set(
            items=(replace(proposal_item(), raw_row_locator=changed_row_locator),)
        )

        self.assertEqual(baseline.semantic_digest, relocated.semantic_digest)
        self.assertNotEqual(baseline.semantic_digest, changed_row.semantic_digest)
        self.assertEqual(
            baseline.items[0].raw_row_locator.observed_absolute_path,
            r"C:\imports\first\segments.jsonl",
        )
        with self.assertRaises(ValidationError):
            RawRowLocator("segments.jsonl#row=1", "relative/segments.jsonl")

    def test_reconstitution_verifies_digest_emits_nothing_and_keeps_values_frozen(self) -> None:
        created = complete_proposal_set()
        values = proposal_values()
        reconstituted = ASRProposalSet.reconstitute(
            **values, semantic_digest=created.semantic_digest  # type: ignore[arg-type]
        )

        self.assertEqual(reconstituted, created)
        self.assertEqual(reconstituted.pull_events(), ())
        with self.assertRaises(FrozenInstanceError):
            reconstituted.imported_at_us = 999  # type: ignore[misc]
        with self.assertRaises(ValidationError):
            ASRProposalSet.reconstitute(
                **values,
                semantic_digest=ContentDigest("sha256", "f" * 64),  # type: ignore[arg-type]
            )

    def test_public_boundaries_reject_mutable_collection_subclasses(self) -> None:
        class MutableTuple(tuple):
            pass

        with self.assertRaises(ValidationError):
            complete_proposal_set(items=MutableTuple((proposal_item(),)))
        with self.assertRaises(ValidationError):
            complete_proposal_set(missing_field_warnings=MutableTuple(()))


if __name__ == "__main__":
    unittest.main()
