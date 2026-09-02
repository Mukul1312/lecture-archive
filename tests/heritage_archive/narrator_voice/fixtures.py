"""Strict, obviously fake Narrator Voice test data builders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from heritage_archive.kernel import ActorId, ArtifactId, ArtifactRef, ContentDigest
from heritage_archive.contexts.narrator_voice.domain.evidence import (
    AuthoritySnapshot,
    DecodedMediaFacts,
    GenerationPreview,
    ListeningOutcome,
    NarrationMaster,
    NarrationMasterListeningDecision,
    NarrationMasterSnapshot,
    PassageOffset,
    NarrationTake,
    PublishedArtifact,
)
from heritage_archive.contexts.narrator_voice.domain.ids import (
    AuthorizationRecordId,
    DiaryEpisodeId,
    GenerationAttemptId,
    GenerationPreviewId,
    MasterListeningDecisionId,
    NarrationMasterId,
    NarrationMasterSnapshotId,
    NarrationJobId,
    PassageId,
    PassageRenderRecipeId,
    TakeId,
)
from heritage_archive.contexts.narrator_voice.domain.values import (
    AuthorityOperation,
    AuthorityScope,
    CanonicalAudioFacts,
    ComponentRole,
    ControlProvenance,
    DeliveryControlDefaults,
    DictionaryBinding,
    EffectiveSynthesisInput,
    EffectiveTakeSettings,
    FixedTwoDecimal,
    Lane,
    PassageRenderRecipe,
    PassageText,
    ReleaseSynthesisContract,
    ResolvedControl,
    SafeRelativeArtifactPath,
)


NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


def uuid(index: int) -> str:
    return f"123e4567-e89b-42d3-a456-42661419{index:04d}"


def digest(label: str) -> ContentDigest:
    return ContentDigest.from_bytes(label.encode("utf-8"))


def make_dictionary(label: str = "a") -> DictionaryBinding:
    return DictionaryBinding(f"fake-dictionary-{label}", digest(f"dictionary-{label}"), f"revision-{label}", f"capability-{label}")


def make_defaults(label: str = "a") -> DeliveryControlDefaults:
    return DeliveryControlDefaults(FixedTwoDecimal("0.90"), FixedTwoDecimal("1.00"), "calm", make_dictionary(label))


def make_settings(label: str = "a") -> EffectiveTakeSettings:
    return EffectiveTakeSettings(
        ResolvedControl(ControlProvenance.INHERITED, "0.90"),
        ResolvedControl(ControlProvenance.INHERITED, "1.00"),
        ResolvedControl(ControlProvenance.INHERITED, "calm"),
        make_dictionary(label),
        ControlProvenance.INHERITED,
    )


def make_scope(*, lane: Lane = Lane.B, episode_id: DiaryEpisodeId | None = None) -> AuthorityScope:
    if lane is Lane.C and episode_id is None:
        episode_id = DiaryEpisodeId(uuid(2))
    return AuthorityScope(
        f"fake-speaker-{lane.value}",
        f"fake-voice-{lane.value}",
        "or",
        "reviewed-odia-diary-intro" if lane is Lane.C else "reviewed-odia-diary",
        episode_id,
        frozenset({AuthorityOperation.PREFLIGHT, AuthorityOperation.GENERATE, AuthorityOperation.ASSEMBLE, AuthorityOperation.ATTACH, AuthorityOperation.DELIVER}),
        NOW,
        NOW + timedelta(days=365),
    )


def make_authority(*, lane: Lane = Lane.B, episode_id: DiaryEpisodeId | None = None, revision: int = 1) -> AuthoritySnapshot:
    scope = make_scope(lane=lane, episode_id=episode_id)
    return AuthoritySnapshot.create(AuthorizationRecordId(uuid(3 if lane is Lane.B else 4)), revision, scope, digest(f"authority-{lane.value}-{revision}"), NOW)


def make_contract(*, lane: Lane = Lane.B, episode_id: DiaryEpisodeId | None = None) -> ReleaseSynthesisContract:
    if lane is Lane.C and episode_id is None:
        episode_id = DiaryEpisodeId(uuid(2))
    return ReleaseSynthesisContract(
        lane,
        "reviewed-odia-diary-intro" if lane is Lane.C else "reviewed-odia-diary",
        f"fake-speaker-{lane.value}",
        f"fake-voice-{lane.value}",
        "fake-provider",
        f"opaque-fake-voice-{lane.value}",
        "or",
        "fake-model-2026-09-02",
        "fake-api-v1",
        "fake-capability-v1",
        AuthorizationRecordId(uuid(3 if lane is Lane.B else 4)),
        CanonicalAudioFacts(),
        ComponentRole.INTRO.value if lane is Lane.C else ComponentRole.DIARY.value,
        episode_id,
    )


def make_recipe(passage_text: PassageText, *, recipe_index: int = 10, revision: int = 1, text_revision: int = 1) -> PassageRenderRecipe:
    return PassageRenderRecipe(
        PassageRenderRecipeId(uuid(recipe_index)), revision, text_revision,
        passage_text.digest, "fake-compiler-v1", (),
    )


def make_esi(
    *,
    job_id: NarrationJobId,
    passage_id: PassageId,
    text: PassageText,
    recipe: PassageRenderRecipe,
    contract: ReleaseSynthesisContract,
    settings: EffectiveTakeSettings | None = None,
    authority: AuthoritySnapshot | None = None,
) -> EffectiveSynthesisInput:
    settings = settings or make_settings()
    authority = authority or make_authority(lane=contract.lane, episode_id=contract.intended_episode_id)
    return EffectiveSynthesisInput.create(
        job_id=job_id,
        lane=contract.lane,
        passage_id=passage_id,
        text_revision=recipe.text_revision,
        text=text,
        recipe_id=recipe.recipe_id,
        recipe_revision=recipe.revision,
        recipe_digest=recipe.digest,
        compiler_version=recipe.compiler_version,
        settings=settings,
        contract_digest=contract.digest,
        authority_scope=authority.scope,
        authority_revision=authority.record_revision,
        authority_digest=authority.record_digest,
        authority_observed_at=authority.observed_at,
        endpoint="fake://no-network",
        api_schema=contract.api_schema,
        capability_snapshot=contract.capability_snapshot,
        rendered_transcript=f"<fake>{text.value}</fake>",
        canonical_projection=text.value,
        timestamps_requested=True,
        normalization="off",
        output_audio=contract.audio,
        billable_rule="fake-billing-v1",
        billable_characters=len(text.value) + 13,
    )


def make_preview(
    *,
    job_id: NarrationJobId,
    base_revision: int,
    passage_id: PassageId,
    text: PassageText,
    recipe: PassageRenderRecipe,
    contract: ReleaseSynthesisContract,
    preview_index: int = 20,
    settings: EffectiveTakeSettings | None = None,
    authority: AuthoritySnapshot | None = None,
) -> GenerationPreview:
    settings = settings or make_settings()
    authority = authority or make_authority(lane=contract.lane, episode_id=contract.intended_episode_id)
    return GenerationPreview.create(
        preview_id=GenerationPreviewId(uuid(preview_index)),
        base_job_revision=base_revision,
        passage_id=passage_id,
        text_revision=recipe.text_revision,
        text_digest=text.digest,
        recipe_id=recipe.recipe_id,
        recipe_revision=recipe.revision,
        recipe_digest=recipe.digest,
        settings=settings,
        contract_digest=contract.digest,
        authority_snapshot=authority,
        compiler_version=recipe.compiler_version,
        capability_snapshot=contract.capability_snapshot,
        endpoint="fake://no-network",
        rendered_transcript=f"<fake>{text.value}</fake>",
        canonical_projection=text.value,
        timestamps_requested=True,
        normalization="off",
        output_audio=contract.audio,
        billable_rule="fake-billing-v1",
        estimated_usage=str(len(text.value) + 13),
        issued_at=NOW,
    )


def make_artifact(index: int, label: str, *, samples: int = 100) -> tuple[PublishedArtifact, DecodedMediaFacts]:
    reference = ArtifactRef(ArtifactId(uuid(index)), digest(label), 44 + samples * 2, "audio/wav")
    return (
        PublishedArtifact(reference, SafeRelativeArtifactPath(f"fake/{label}.wav"), NOW),
        DecodedMediaFacts(CanonicalAudioFacts(), samples, max(1, samples * 1000 // 44_100), False),
    )


def make_take(
    *,
    job_id: NarrationJobId,
    passage_id: PassageId,
    text: PassageText,
    recipe: PassageRenderRecipe,
    contract: ReleaseSynthesisContract,
    take_index: int = 30,
    attempt_index: int = 31,
    settings: EffectiveTakeSettings | None = None,
    authority: AuthoritySnapshot | None = None,
) -> NarrationTake:
    settings = settings or make_settings()
    authority = authority or make_authority(lane=contract.lane, episode_id=contract.intended_episode_id)
    esi = make_esi(job_id=job_id, passage_id=passage_id, text=text, recipe=recipe, contract=contract, settings=settings, authority=authority)
    publication, media = make_artifact(32 + take_index, f"take-{take_index}")
    return NarrationTake(
        TakeId(uuid(take_index)), GenerationAttemptId(uuid(attempt_index)), job_id,
        contract.lane, passage_id, recipe.text_revision, text.digest,
        recipe.recipe_id, recipe.revision, recipe.digest, settings, contract.digest,
        authority, esi, publication, media, None, NOW,
    )


def make_master_snapshot(
    *,
    lane: Lane,
    episode_id: DiaryEpisodeId | None,
    index: int,
    samples: int,
) -> NarrationMasterSnapshot:
    contract = make_contract(lane=lane, episode_id=episode_id)
    job_id = NarrationJobId(uuid(index))
    passage_id = PassageId(uuid(index + 1))
    take_id = TakeId(uuid(index + 2))
    publication, media = make_artifact(index + 3, f"snapshot-master-{index}", samples=samples)
    offset = PassageOffset(passage_id, 1, digest(f"snapshot-text-{index}"), 0, samples)
    master = NarrationMaster(
        NarrationMasterId(uuid(index + 4)), job_id, lane, contract.digest,
        (take_id,), (), (offset,), publication, media, NOW,
    )
    listening = NarrationMasterListeningDecision(
        MasterListeningDecisionId(uuid(index + 5)), master.master_id,
        ActorId(uuid(index + 6)), ListeningOutcome.PASSED,
        f"fake listened {index}", NOW,
    )
    return NarrationMasterSnapshot.create(
        snapshot_id=NarrationMasterSnapshotId(uuid(index + 7)),
        issuing_job_id=job_id,
        issuing_job_revision=9,
        source_master=master,
        listening_decision=listening,
        authority_snapshot=make_authority(lane=lane, episode_id=episode_id),
        role=ComponentRole.INTRO if lane is Lane.C else ComponentRole.DIARY,
        intended_episode_id=episode_id if lane is Lane.C else None,
        ordered_passage_ids=(passage_id,),
        selected_take_ids=(take_id,),
        issued_at=NOW,
    )
