"""Cross-stage evidence and strict schema-v1 contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ActorId, ArtifactId, ArtifactRef, ContentDigest, ValidationError
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AttemptKind,
    AttemptState,
    AttemptWorkspaceEvidence,
    AuthoritySnapshot,
    ComponentOffset,
    CueGranularity,
    CueProvenance,
    DecodedMediaFacts,
    EligibilityFacts,
    EpisodeAssemblyAttempt,
    EpisodeListeningDecision,
    EpisodeSpeechMaster,
    GenerationAttempt,
    GenerationPreview,
    ListeningOutcome,
    NarrationAssemblyAttempt,
    NarrationMaster,
    NarrationMasterListeningDecision,
    NarrationMasterSnapshot,
    NarrationTake,
    PassageOffset,
    ProviderEventEvidence,
    ProviderEventKind,
    ProviderTerminalClass,
    PublishedArtifact,
    ReviewAuthority,
    ReviewDecision,
    ReviewOutcome,
    SelectionDecision,
    SubmissionEvidence,
    TimedNarrationPackage,
    TimingCue,
    TimingReviewStatus,
    episode_assembly_plan_digest,
    narration_assembly_plan_digest,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AttemptWorkspaceId,
    AuthorizationRecordId,
    BudgetReservationId,
    CueId,
    DiaryEpisodeId,
    EpisodeAssemblyAttemptId,
    EpisodeListeningDecisionId,
    EpisodeSpeechMasterId,
    GenerationAttemptId,
    GenerationPreviewId,
    MasterListeningDecisionId,
    NarrationAssemblyAttemptId,
    NarrationJobId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    PassageId,
    PassageRenderRecipeId,
    ProviderEventId,
    ReviewDecisionId,
    SelectionDecisionId,
    TakeId,
    TimedNarrationPackageId,
)
from heritage_archive.contexts.narrator_voice.domain.values import (
    AuthorityOperation,
    AuthorityScope,
    CanonicalAudioFacts,
    ComponentRole,
    ControlProvenance,
    DictionaryBinding,
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    Lane,
    PassageText,
    ResolvedControl,
    SafeRelativeArtifactPath,
)
from heritage_archive.contexts.narrator_voice.application.schema_v1 import (
    decode_schema_v1,
    encode_schema_v1,
    schema_v1_payload,
)


UUIDS = [f"123e4567-e89b-42d3-a456-42661417{n:04d}" for n in range(100)]
NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


def digest(label: str) -> ContentDigest:
    return ContentDigest.from_bytes(label.encode("utf-8"))


def artifact(index: int, label: str, samples: int = 100) -> tuple[PublishedArtifact, DecodedMediaFacts]:
    ref = ArtifactRef(ArtifactId(UUIDS[index]), digest(label), samples * 2 + 44, "audio/wav")
    publication = PublishedArtifact(ref, SafeRelativeArtifactPath(f"fake/{label}.wav"), NOW)
    media = DecodedMediaFacts(CanonicalAudioFacts(), samples, max(1, samples * 1000 // 44100), False)
    return publication, media


def authority_snapshot() -> AuthoritySnapshot:
    scope = AuthorityScope(
        "speaker-binding",
        "voice-binding",
        "or",
        "reviewed-odia-diary",
        None,
        frozenset({AuthorityOperation.GENERATE, AuthorityOperation.ASSEMBLE, AuthorityOperation.DELIVER}),
        NOW,
        datetime(2027, 9, 2, tzinfo=timezone.utc),
    )
    return AuthoritySnapshot.create(AuthorizationRecordId(UUIDS[1]), 3, scope, digest("authority-record"), NOW)


def effective_input() -> EffectiveSynthesisInput:
    text = PassageText("ଅଆ")
    dictionary = DictionaryBinding("fake-dictionary", digest("dictionary"), "r1", "cap1")
    settings = EffectiveTakeSettings(
        ResolvedControl(ControlProvenance.INHERITED, "0.90"),
        ResolvedControl(ControlProvenance.INHERITED, "1.00"),
        ResolvedControl(ControlProvenance.EXPLICITLY_OMITTED, None),
        dictionary,
        ControlProvenance.INHERITED,
    )
    authority = authority_snapshot()
    return EffectiveSynthesisInput.create(
        job_id=NarrationJobId(UUIDS[2]),
        lane=Lane.B,
        passage_id=PassageId(UUIDS[3]),
        text_revision=1,
        text=text,
        recipe_id=PassageRenderRecipeId(UUIDS[4]),
        recipe_revision=1,
        recipe_digest=digest("recipe"),
        compiler_version="fake-compiler-v1",
        settings=settings,
        contract_digest=digest("contract"),
        authority_scope=authority.scope,
        authority_revision=authority.record_revision,
        authority_digest=authority.record_digest,
        authority_observed_at=NOW,
        endpoint="fake://no-network",
        api_schema="fake-api-v1",
        capability_snapshot="fake-capability-v1",
        rendered_transcript="<fake>ଅଆ</fake>",
        canonical_projection=text.value,
        timestamps_requested=True,
        normalization="off",
        output_audio=CanonicalAudioFacts(),
        billable_rule="fake-billing-v1",
        billable_characters=15,
    )


def preview() -> GenerationPreview:
    esi = effective_input()
    return GenerationPreview.create(
        preview_id=GenerationPreviewId(UUIDS[5]),
        base_job_revision=4,
        passage_id=esi.passage_id,
        text_revision=esi.text_revision,
        text_digest=esi.text.digest,
        recipe_id=esi.recipe_id,
        recipe_revision=esi.recipe_revision,
        recipe_digest=esi.recipe_digest,
        settings=esi.settings,
        contract_digest=esi.contract_digest,
        authority_snapshot=authority_snapshot(),
        compiler_version=esi.compiler_version,
        capability_snapshot=esi.capability_snapshot,
        endpoint=esi.endpoint,
        rendered_transcript=esi.rendered_transcript,
        canonical_projection=esi.canonical_projection,
        timestamps_requested=True,
        normalization="off",
        output_audio=CanonicalAudioFacts(),
        billable_rule="fake-billing-v1",
        billable_characters=15,
        estimated_usage="15",
        issued_at=NOW,
    )


class EvidenceContractTests(unittest.TestCase):
    def test_assembly_attempt_records_reject_untyped_or_structurally_incomplete_schema_facts(self) -> None:
        with self.assertRaises(ValidationError):
            NarrationAssemblyAttempt(
                NarrationAssemblyAttemptId(UUIDS[0]), 1, (), (), "reserved",  # type: ignore[arg-type]
                None, None, (), None, None, NOW, NOW,
            )
        with self.assertRaises(ValidationError):
            EpisodeAssemblyAttempt(
                EpisodeAssemblyAttemptId(UUIDS[1]), 1, (digest("only-one"),), 0,
                AttemptState.RESERVED, None, None, (), None, None, NOW, NOW,
            )
        publication, media = artifact(90, "single-component-episode", 100)
        single = ComponentOffset(ComponentRole.INTRO, 0, 100, digest("intro-only"), ())
        with self.assertRaises(ValidationError):
            EpisodeSpeechMaster(
                EpisodeSpeechMasterId(UUIDS[91]), DiaryEpisodeId(UUIDS[92]),
                (digest("intro"), digest("diary")), 0, (single,), publication, media, NOW,
            )

    def test_preview_digest_binds_exact_rendered_bytes_and_constituent_digests(self) -> None:
        value = preview()
        self.assertEqual(value.rendered_transcript_bytes, b"<fake>\xe0\xac\x85\xe0\xac\x86</fake>")
        self.assertEqual(value.rendered_transcript_digest, ContentDigest.from_bytes(value.rendered_transcript_bytes))
        self.assertIsInstance(value.preview_digest, ContentDigest)
        with self.assertRaises(ValidationError):
            replace(value, rendered_transcript="different")

    def test_provider_events_attempts_and_workspace_preserve_ordered_submission_evidence(self) -> None:
        raw_ref = ArtifactRef(ArtifactId(UUIDS[6]), digest("event"), 12, "application/json")
        event = ProviderEventEvidence(
            ProviderEventId(UUIDS[7]),
            0,
            ProviderEventKind.TERMINAL,
            raw_ref,
            digest("event"),
            NOW,
            "fake-request",
            "fake-response",
            None,
            None,
            "15",
            ProviderTerminalClass.SUCCESS,
        )
        workspace = AttemptWorkspaceEvidence(
            AttemptWorkspaceId(UUIDS[8]),
            AttemptKind.GENERATION,
            NarrationJobId(UUIDS[2]),
            GenerationAttemptId(UUIDS[9]),
            5,
            BudgetReservationId(UUIDS[10]),
            preview().preview_digest,
            effective_input().request_digest,
            effective_input().request_digest,
            SubmissionEvidence.COMPLETED,
            (event,),
            (),
            (),
            ("fake-complete-evidence",),
            AttemptState.COMPLETED,
        )
        self.assertEqual(workspace.events[0].sequence, 0)
        with self.assertRaises(ValidationError):
            replace(workspace, events=(replace(event, sequence=1),))
        with self.assertRaises(ValidationError):
            replace(workspace, aggregate_id=DiaryEpisodeId(UUIDS[2]))
        with self.assertRaises(ValidationError):
            replace(workspace, frozen_plan_digest=digest("wrong-plan"))
        with self.assertRaises(ValidationError):
            replace(
                workspace,
                effective_input_digest=None,
                frozen_plan_digest=None,
                state=AttemptState.INPUT_FROZEN,
            )

    def test_assembly_plan_digests_are_domain_separated_and_validate_exact_inputs(self) -> None:
        narration = narration_assembly_plan_digest(
            (TakeId(UUIDS[11]), TakeId(UUIDS[12])), (220,)
        )
        episode = episode_assembly_plan_digest((digest("intro"), digest("diary")), 220)
        self.assertNotEqual(narration, episode)
        with self.assertRaises(ValidationError):
            narration_assembly_plan_digest((TakeId(UUIDS[11]),), (1,))
        with self.assertRaises(ValidationError):
            episode_assembly_plan_digest((digest("only"),), 0)

    def test_generation_attempt_states_reject_impossible_completed_or_temporal_facts(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationAttempt(
                GenerationAttemptId(UUIDS[9]), PassageId(UUIDS[3]), 5,
                BudgetReservationId(UUIDS[10]), GenerationPreviewId(UUIDS[5]),
                preview().preview_digest, AttemptState.COMPLETED,
                SubmissionEvidence.COMPLETED, effective_input(), (), None, None,
                None, None, NOW, NOW,
            )

    def test_decoded_media_duration_is_the_canonical_projection_of_exact_samples(self) -> None:
        self.assertEqual(DecodedMediaFacts(CanonicalAudioFacts(), 44_100, 1_000, False).duration_ms, 1_000)
        with self.assertRaises(ValidationError):
            DecodedMediaFacts(CanonicalAudioFacts(), 100, 3, False)

    def test_media_offset_take_master_snapshot_episode_and_timing_evidence_is_immutable(self) -> None:
        publication, media = artifact(11, "take")
        esi = effective_input()
        eligibility = EligibilityFacts(False, False, False, False, False)
        take = NarrationTake(
            TakeId(UUIDS[12]), GenerationAttemptId(UUIDS[9]), esi.job_id, esi.lane,
            esi.passage_id, esi.text_revision, esi.text.digest, esi.recipe_id,
            esi.recipe_revision, esi.recipe_digest, esi.settings, esi.contract_digest,
            authority_snapshot(), esi, publication, media, None, NOW,
        )
        review = ReviewDecision(
            ReviewDecisionId(UUIDS[13]), take.take_id, ActorId(UUIDS[14]),
            ReviewAuthority.OPERATIONAL, ReviewOutcome.ACCEPTED, "fake review", NOW,
        )
        selection = SelectionDecision(
            SelectionDecisionId(UUIDS[15]), esi.passage_id, take.take_id,
            ActorId(UUIDS[14]), eligibility, "fake selection reason", NOW,
        )
        offset = PassageOffset(esi.passage_id, esi.text_revision, esi.text.digest, 0, media.sample_count)
        master_artifact, master_media = artifact(16, "master")
        master = NarrationMaster(
            NarrationMasterId(UUIDS[17]), esi.job_id, esi.lane, esi.contract_digest,
            (take.take_id,), (), (offset,), (take.timing_reference,), master_artifact, master_media, NOW,
        )
        listening = NarrationMasterListeningDecision(
            MasterListeningDecisionId(UUIDS[18]), master.master_id, ActorId(UUIDS[14]),
            ListeningOutcome.PASSED, "fake complete listening", NOW,
        )
        snapshot = NarrationMasterSnapshot.create(
            snapshot_id=NarrationMasterSnapshotId(UUIDS[19]),
            issuing_job_id=esi.job_id,
            issuing_job_revision=12,
            source_master=master,
            listening_decision=listening,
            authority_snapshot=authority_snapshot(),
            role=ComponentRole.DIARY,
            intended_episode_id=None,
            ordered_passage_ids=(esi.passage_id,),
            selected_take_ids=(take.take_id,),
            issued_at=NOW,
        )
        intro_digest = digest("intro-snapshot")
        intro_component = ComponentOffset(ComponentRole.INTRO, 0, 50, intro_digest, ())
        component = ComponentOffset(
            ComponentRole.DIARY,
            100,
            100 + master_media.sample_count,
            snapshot.snapshot_digest,
            (replace(offset, start_sample=100, end_sample=100 + media.sample_count),),
        )
        episode_artifact, episode_media = artifact(20, "episode", 200)
        episode_master = EpisodeSpeechMaster(
            EpisodeSpeechMasterId(UUIDS[21]), DiaryEpisodeId(UUIDS[22]),
            (intro_digest, snapshot.snapshot_digest), 50, (intro_component, component), episode_artifact,
            episode_media, NOW,
        )
        episode_listening = EpisodeListeningDecision(
            EpisodeListeningDecisionId(UUIDS[23]), episode_master.master_id,
            ActorId(UUIDS[14]), ListeningOutcome.PASSED, "fake episode listening", NOW,
        )
        cue = TimingCue(
            CueId(UUIDS[24]), ComponentRole.DIARY, Lane.B, esi.job_id,
            master.master_id, esi.passage_id, esi.text_revision, esi.text.digest,
            esi.text.value, None, 100, 200, CueGranularity.PASSAGE,
            CueProvenance.DETERMINISTIC_ASSEMBLY, "fake-normalizer", "v1",
            episode_artifact.reference.content_digest, esi.text.digest,
            TimingReviewStatus.VALIDATED,
        )
        package = TimedNarrationPackage.create(
            package_id=TimedNarrationPackageId(UUIDS[25]),
            version=1,
            episode_id=episode_master.episode_id,
            episode_revision=8,
            episode_master=episode_master,
            intro_snapshot_digest=intro_digest,
            diary_snapshot_digest=snapshot.snapshot_digest,
            cues=(cue,),
            raw_timing_artifacts=(),
            normalized_timing_artifact=None,
            validation_results=("component-and-passage-cues-valid",),
            timing_review_status=TimingReviewStatus.VALIDATED,
            authority_snapshots=(authority_snapshot(), authority_snapshot()),
            source_package_digest=None,
            correction_actor_id=None,
            correction_reason=None,
            created_at=NOW,
        )
        self.assertEqual((review.outcome, selection.take_id, snapshot.role, episode_listening.outcome), (ReviewOutcome.ACCEPTED, take.take_id, ComponentRole.DIARY, ListeningOutcome.PASSED))
        self.assertEqual(package.cues[0].start_sample, 100)
        self.assertIsInstance(package.package_digest, ContentDigest)


class SchemaV1Tests(unittest.TestCase):
    def test_all_cross_stage_records_round_trip_as_strict_canonical_primitives(self) -> None:
        publication, media = artifact(30, "schema")
        values = (authority_snapshot(), preview(), publication, media)
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                encoded = encode_schema_v1(value)
                decoded = decode_schema_v1(encoded, type(value))
                self.assertEqual(decoded, value)
                self.assertEqual(encode_schema_v1(decoded), encoded)
                self.assert_primitives_have_no_float_or_decimal(schema_v1_payload(value))

    def test_unknown_schema_versions_fields_and_noncanonical_numbers_are_rejected(self) -> None:
        encoded = encode_schema_v1(authority_snapshot())
        for broken in (
            encoded.replace(b'"schema_version":1', b'"schema_version":2'),
            encoded[:-1] + b',"unknown":true}',
            encoded.replace(b'"record_revision":3', b'"record_revision":3.0'),
        ):
            with self.subTest(broken=broken[-60:]):
                with self.assertRaises(ValidationError):
                    decode_schema_v1(broken, AuthoritySnapshot)
        payload = schema_v1_payload(authority_snapshot())
        payload["unknown"] = True
        with self.assertRaises(ValidationError):
            decode_schema_v1(encode_schema_v1(payload), AuthoritySnapshot)

    def test_decoder_rejects_noncanonical_json_bytes_and_alternate_utc_spellings(self) -> None:
        encoded = encode_schema_v1(authority_snapshot())
        with self.assertRaises(ValidationError):
            decode_schema_v1(b" " + encoded, AuthoritySnapshot)
        alternate_utc = encoded.replace(b"2026-09-02T12:00:00+00:00", b"2026-09-02T12:00:00Z")
        self.assertNotEqual(alternate_utc, encoded)
        with self.assertRaises(ValidationError):
            decode_schema_v1(alternate_utc, AuthoritySnapshot)

    def assert_primitives_have_no_float_or_decimal(self, value: object) -> None:
        self.assertNotIsInstance(value, (float, Decimal))
        if type(value) is list:
            for member in value:
                self.assert_primitives_have_no_float_or_decimal(member)
        elif type(value) is dict:
            for member in value.values():
                self.assert_primitives_have_no_float_or_decimal(member)


if __name__ == "__main__":
    unittest.main()
