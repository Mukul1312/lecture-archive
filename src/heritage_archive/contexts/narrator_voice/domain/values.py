"""Immutable values shared by the three Narrator Voice aggregate roots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import TypeAlias

from heritage_archive.kernel import (
    ContentDigest,
    ValidationError,
    require_canonical_text,
    semantic_digest,
)

from .ids import (
    AuthorizationRecordId,
    DiaryEpisodeId,
    NarrationJobId,
    PassageId,
    PassageRenderRecipeId,
)


def _required_text(value: object, field: str) -> str:
    return require_canonical_text(value, field=field, nonempty=True)


def _utc(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field} must be an aware UTC datetime")
    return value


class Lane(str, Enum):
    B = "lane_b"
    C = "lane_c"


class ComponentRole(str, Enum):
    INTRO = "intro"
    DIARY = "diary"


class AuthorityOperation(str, Enum):
    PREFLIGHT = "preflight"
    GENERATE = "generate"
    ASSEMBLE = "assemble"
    ATTACH = "attach"
    DELIVER = "deliver"


class ControlProvenance(str, Enum):
    INHERITED = "inherited"
    EXPLICITLY_SET = "explicitly_set"
    EXPLICITLY_OMITTED = "explicitly_omitted"


_FIXED_TWO = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{2}$")
_CANONICAL_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")


@dataclass(frozen=True, slots=True)
class FixedTwoDecimal:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _FIXED_TWO.fullmatch(self.value) is None:
            raise ValidationError("request control must be an unsigned canonical fixed two-decimal string")


@dataclass(frozen=True, slots=True)
class NonNegativeDecimal:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _CANONICAL_DECIMAL.fullmatch(self.value) is None:
            raise ValidationError("money or usage must be a canonical nonnegative decimal string")


@dataclass(frozen=True, slots=True)
class PassageText:
    value: str

    def __post_init__(self) -> None:
        value = _required_text(self.value, "passage text")
        if len(value) > 8_000:
            raise ValidationError("passage text exceeds 8,000 Unicode scalars")
        # INV-NJ-11: canonical review/display text never carries provider markup.
        if "<" in value or ">" in value:
            raise ValidationError("passage text must not contain provider markup")

    @property
    def scalar_length(self) -> int:
        return len(self.value)

    @property
    def digest(self) -> ContentDigest:
        return ContentDigest.from_bytes(self.value.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class TextSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int:
            raise ValidationError("text span coordinates must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValidationError("text spans must be nonempty half-open scalar ranges")

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class BreakControl:
    boundary: int
    duration_ms: int

    def __post_init__(self) -> None:
        if type(self.boundary) is not int or self.boundary < 0:
            raise ValidationError("break boundary must be a nonnegative scalar offset")
        if type(self.duration_ms) is not int or not 10 <= self.duration_ms <= 5_000:
            raise ValidationError("break duration must be an integer from 10 through 5,000 ms")


@dataclass(frozen=True, slots=True)
class SpeedControl:
    span: TextSpan
    value: FixedTwoDecimal

    def __post_init__(self) -> None:
        if type(self.span) is not TextSpan or type(self.value) is not FixedTwoDecimal:
            raise ValidationError("speed control requires a TextSpan and FixedTwoDecimal")


@dataclass(frozen=True, slots=True)
class VolumeControl:
    span: TextSpan
    value: FixedTwoDecimal

    def __post_init__(self) -> None:
        if type(self.span) is not TextSpan or type(self.value) is not FixedTwoDecimal:
            raise ValidationError("volume control requires a TextSpan and FixedTwoDecimal")


@dataclass(frozen=True, slots=True)
class SpellingControl:
    span: TextSpan
    spelling: str

    def __post_init__(self) -> None:
        if type(self.span) is not TextSpan:
            raise ValidationError("spelling control requires a TextSpan")
        _required_text(self.spelling, "spelling intent")
        if self.span.length > 64:
            raise ValidationError("spelling spans may contain at most 64 Unicode scalars")


RenderControl: TypeAlias = BreakControl | SpeedControl | VolumeControl | SpellingControl


def _control_key(control: RenderControl) -> tuple[int, int, int]:
    if type(control) is BreakControl:
        return control.boundary, 1, control.boundary
    ranks = {VolumeControl: 0, SpeedControl: 2, SpellingControl: 3}
    return control.span.start, ranks[type(control)], control.span.end


@dataclass(frozen=True, slots=True)
class PassageRenderRecipe:
    recipe_id: PassageRenderRecipeId
    revision: int
    text_revision: int
    text_digest: ContentDigest
    compiler_version: str
    controls: tuple[RenderControl, ...]

    def __post_init__(self) -> None:
        if type(self.recipe_id) is not PassageRenderRecipeId:
            raise ValidationError("recipe_id must be a PassageRenderRecipeId")
        if type(self.revision) is not int or self.revision < 1:
            raise ValidationError("recipe revision must be a positive integer")
        if type(self.text_revision) is not int or self.text_revision < 1:
            raise ValidationError("recipe text revision must be a positive integer")
        if type(self.text_digest) is not ContentDigest:
            raise ValidationError("recipe text_digest must be a ContentDigest")
        _required_text(self.compiler_version, "compiler version")
        if type(self.controls) is not tuple:
            raise ValidationError("recipe controls must be an immutable tuple")
        if any(type(control) not in {BreakControl, SpeedControl, VolumeControl, SpellingControl} for control in self.controls):
            raise ValidationError("recipe contains an unknown render control")
        if len(self.controls) > 64:
            raise ValidationError("a recipe may contain at most 64 controls")
        object.__setattr__(self, "controls", tuple(sorted(self.controls, key=_control_key)))

    @property
    def digest(self) -> ContentDigest:
        controls: list[dict[str, object]] = []
        for control in self.controls:
            if type(control) is BreakControl:
                controls.append({"kind": "break", "boundary": control.boundary, "duration_ms": control.duration_ms})
            elif type(control) is SpeedControl:
                controls.append({"kind": "speed", "start": control.span.start, "end": control.span.end, "value": control.value.value})
            elif type(control) is VolumeControl:
                controls.append({"kind": "volume", "start": control.span.start, "end": control.span.end, "value": control.value.value})
            else:
                controls.append({"kind": "spelling", "start": control.span.start, "end": control.span.end, "spelling": control.spelling})
        return semantic_digest(
            "narrator_voice.passage_render_recipe.v1",
            {
                "recipe_id": self.recipe_id.value,
                "revision": self.revision,
                "text_revision": self.text_revision,
                "text_digest": self.text_digest.hex_digest,
                "compiler_version": self.compiler_version,
                "controls": controls,
            },
        )

    def validate_for(self, text: PassageText) -> None:
        if type(text) is not PassageText or text.digest != self.text_digest:
            raise ValidationError("recipe must bind the exact canonical passage text")
        families = (BreakControl, SpeedControl, VolumeControl, SpellingControl)
        for family in families:
            if sum(type(control) is family for control in self.controls) > 16:
                raise ValidationError(f"a recipe may contain at most 16 {family.__name__} values")
        breaks = [control for control in self.controls if type(control) is BreakControl]
        if sum(control.duration_ms for control in breaks) > 20_000:
            raise ValidationError("total inserted break duration may not exceed 20,000 ms")
        for control in self.controls:
            if type(control) is BreakControl:
                if control.boundary > text.scalar_length:
                    raise ValidationError("break boundary is outside passage text")
            elif control.span.end > text.scalar_length:
                raise ValidationError("render-control span is outside passage text")
        for family in (SpeedControl, VolumeControl, SpellingControl):
            spans = [control.span for control in self.controls if type(control) is family]
            for left, right in zip(spans, spans[1:]):
                if right.start < left.end:
                    raise ValidationError(f"same-kind {family.__name__} spans may not overlap")


@dataclass(frozen=True, slots=True)
class DictionaryBinding:
    opaque_reference: str
    content_digest: ContentDigest
    revision: str
    capability_identity: str

    def __post_init__(self) -> None:
        _required_text(self.opaque_reference, "opaque dictionary reference")
        if type(self.content_digest) is not ContentDigest:
            raise ValidationError("dictionary content_digest must be a ContentDigest")
        _required_text(self.revision, "dictionary revision")
        _required_text(self.capability_identity, "dictionary capability identity")


@dataclass(frozen=True, slots=True)
class ResolvedControl:
    provenance: ControlProvenance
    value: str | None

    def __post_init__(self) -> None:
        if type(self.provenance) is not ControlProvenance:
            raise ValidationError("control provenance is invalid")
        if self.provenance is ControlProvenance.EXPLICITLY_OMITTED:
            if self.value is not None:
                raise ValidationError("an explicitly omitted control has no value")
        elif self.value is None:
            raise ValidationError("an inherited or explicitly set control requires a value")
        else:
            _required_text(self.value, "resolved control value")


@dataclass(frozen=True, slots=True)
class DeliveryControlDefaults:
    speed: FixedTwoDecimal
    volume: FixedTwoDecimal
    emotion: str | None
    dictionary: DictionaryBinding | None

    def __post_init__(self) -> None:
        if type(self.speed) is not FixedTwoDecimal or type(self.volume) is not FixedTwoDecimal:
            raise ValidationError("delivery defaults require fixed-two-decimal speed and volume")
        if self.emotion is not None:
            _required_text(self.emotion, "default emotion")
        if self.dictionary is not None and type(self.dictionary) is not DictionaryBinding:
            raise ValidationError("default dictionary must be a DictionaryBinding or null")


@dataclass(frozen=True, slots=True)
class EffectiveTakeSettings:
    speed: ResolvedControl
    volume: ResolvedControl
    emotion: ResolvedControl
    dictionary: DictionaryBinding | None
    dictionary_provenance: ControlProvenance

    def __post_init__(self) -> None:
        if type(self.speed) is not ResolvedControl or type(self.volume) is not ResolvedControl or type(self.emotion) is not ResolvedControl:
            raise ValidationError("effective settings require resolved controls")
        if self.speed.value is None or self.volume.value is None:
            raise ValidationError("speed and volume cannot be omitted")
        FixedTwoDecimal(self.speed.value)
        FixedTwoDecimal(self.volume.value)
        if self.dictionary is not None and type(self.dictionary) is not DictionaryBinding:
            raise ValidationError("effective dictionary must be a DictionaryBinding or null")
        if type(self.dictionary_provenance) is not ControlProvenance:
            raise ValidationError("dictionary provenance is invalid")
        if self.dictionary_provenance is ControlProvenance.EXPLICITLY_OMITTED and self.dictionary is not None:
            raise ValidationError("an explicitly omitted dictionary must be null")
        if self.dictionary_provenance is not ControlProvenance.EXPLICITLY_OMITTED and self.dictionary is None:
            raise ValidationError("an inherited or explicitly set dictionary requires a binding")

    @property
    def digest(self) -> ContentDigest:
        return semantic_digest(
            "narrator_voice.effective_take_settings.v1",
            {
                "speed": {"provenance": self.speed.provenance.value, "value": self.speed.value},
                "volume": {"provenance": self.volume.provenance.value, "value": self.volume.value},
                "emotion": {"provenance": self.emotion.provenance.value, "value": self.emotion.value},
                "dictionary": None if self.dictionary is None else {
                    "opaque_reference": self.dictionary.opaque_reference,
                    "digest": self.dictionary.content_digest.hex_digest,
                    "revision": self.dictionary.revision,
                    "capability": self.dictionary.capability_identity,
                },
                "dictionary_provenance": self.dictionary_provenance.value,
            },
        )


@dataclass(frozen=True, slots=True)
class CanonicalAudioFacts:
    container: str = "wav"
    encoding: str = "pcm_s16le"
    sample_width_bits: int = 16
    byte_order: str = "little"
    channels: int = 1
    sample_rate_hz: int = 44_100

    def __post_init__(self) -> None:
        if (
            self.container,
            self.encoding,
            self.sample_width_bits,
            self.byte_order,
            self.channels,
            self.sample_rate_hz,
        ) != ("wav", "pcm_s16le", 16, "little", 1, 44_100):
            raise ValidationError("canonical audio must be mono 44.1-kHz signed PCM16 little-endian WAV")


@dataclass(frozen=True, slots=True)
class SafeRelativeArtifactPath:
    value: str

    def __post_init__(self) -> None:
        value = _required_text(self.value, "artifact location")
        parts = value.split("/")
        windows_reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{index}" for index in range(1, 10)),
            *(f"LPT{index}" for index in range(1, 10)),
        }
        if (
            "\\" in value
            or ":" in value
            or value.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or len(value.encode("utf-8")) > 1_024
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(len(part.encode("utf-8")) > 255 for part in parts)
            or any(part.endswith((" ", ".")) for part in parts)
            or any(part.split(".", 1)[0].upper() in windows_reserved for part in parts)
        ):
            raise ValidationError("artifact location must be a canonical safe relative POSIX path")


@dataclass(frozen=True, slots=True)
class AuthorityScope:
    speaker_binding: str
    voice_binding: str
    language: str
    purpose: str
    intended_episode_id: DiaryEpisodeId | None
    operations: frozenset[AuthorityOperation]
    valid_from: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _required_text(self.speaker_binding, "authority speaker binding")
        _required_text(self.voice_binding, "authority voice binding")
        _required_text(self.language, "authority language")
        _required_text(self.purpose, "authority purpose")
        if self.intended_episode_id is not None and type(self.intended_episode_id) is not DiaryEpisodeId:
            raise ValidationError("intended episode must be a DiaryEpisodeId or null")
        if type(self.operations) is not frozenset or not self.operations or any(type(item) is not AuthorityOperation for item in self.operations):
            raise ValidationError("authority operations must be a nonempty immutable operation set")
        _utc(self.valid_from, "authority valid_from")
        _utc(self.valid_until, "authority valid_until")
        if self.valid_until <= self.valid_from:
            raise ValidationError("authority validity must have positive duration")

    @property
    def digest(self) -> ContentDigest:
        return semantic_digest(
            "narrator_voice.authority_scope.v1",
            {
                "speaker_binding": self.speaker_binding,
                "voice_binding": self.voice_binding,
                "language": self.language,
                "purpose": self.purpose,
                "intended_episode_id": None if self.intended_episode_id is None else self.intended_episode_id.value,
                "operations": sorted(operation.value for operation in self.operations),
                "valid_from": self.valid_from.isoformat(),
                "valid_until": self.valid_until.isoformat(),
            },
        )

    def covers(self, operation: AuthorityOperation, observed_at: datetime) -> bool:
        _utc(observed_at, "authority observation time")
        return operation in self.operations and self.valid_from <= observed_at < self.valid_until

    def is_narrowing_of(self, prior: AuthorityScope) -> bool:
        if type(prior) is not AuthorityScope:
            return False
        identity = (
            self.speaker_binding,
            self.voice_binding,
            self.language,
            self.purpose,
            self.intended_episode_id,
        )
        prior_identity = (
            prior.speaker_binding,
            prior.voice_binding,
            prior.language,
            prior.purpose,
            prior.intended_episode_id,
        )
        return (
            identity == prior_identity
            and self.operations <= prior.operations
            and self.valid_from >= prior.valid_from
            and self.valid_until <= prior.valid_until
        )


@dataclass(frozen=True, slots=True)
class ReleaseSynthesisContract:
    lane: Lane
    purpose: str
    speaker_binding: str
    voice_binding: str
    provider: str
    opaque_provider_voice_ref: str
    language: str
    model_snapshot: str
    api_schema: str
    capability_snapshot: str
    authority_record_id: AuthorizationRecordId
    audio: CanonicalAudioFacts
    permitted_role: str
    intended_episode_id: DiaryEpisodeId | None

    def __post_init__(self) -> None:
        if type(self.lane) is not Lane:
            raise ValidationError("release contract lane is invalid")
        for field, value in (
            ("purpose", self.purpose),
            ("speaker binding", self.speaker_binding),
            ("voice binding", self.voice_binding),
            ("provider", self.provider),
            ("opaque provider voice reference", self.opaque_provider_voice_ref),
            ("language", self.language),
            ("model snapshot", self.model_snapshot),
            ("API schema", self.api_schema),
            ("capability snapshot", self.capability_snapshot),
            ("permitted role", self.permitted_role),
        ):
            _required_text(value, field)
        if self.language != "or":
            raise ValidationError("the accepted first release language is or")
        if type(self.authority_record_id) is not AuthorizationRecordId:
            raise ValidationError("release contract requires an AuthorizationRecordId")
        if type(self.audio) is not CanonicalAudioFacts:
            raise ValidationError("release contract requires canonical audio facts")
        if self.lane is Lane.B:
            if self.permitted_role != ComponentRole.DIARY.value or self.intended_episode_id is not None:
                raise ValidationError("Lane B contracts are diary-only and not episode-bound")
        elif self.permitted_role != ComponentRole.INTRO.value or type(self.intended_episode_id) is not DiaryEpisodeId:
            raise ValidationError("Lane C contracts are intro-only and bind one intended episode")

    @property
    def digest(self) -> ContentDigest:
        return semantic_digest(
            "narrator_voice.release_synthesis_contract.v1",
            {
                "lane": self.lane.value,
                "purpose": self.purpose,
                "speaker_binding": self.speaker_binding,
                "voice_binding": self.voice_binding,
                "provider": self.provider,
                "opaque_provider_voice_ref": self.opaque_provider_voice_ref,
                "language": self.language,
                "model_snapshot": self.model_snapshot,
                "api_schema": self.api_schema,
                "capability_snapshot": self.capability_snapshot,
                "authority_record_id": self.authority_record_id.value,
                "audio": {
                    "container": self.audio.container,
                    "encoding": self.audio.encoding,
                    "sample_width_bits": self.audio.sample_width_bits,
                    "byte_order": self.audio.byte_order,
                    "channels": self.audio.channels,
                    "sample_rate_hz": self.audio.sample_rate_hz,
                },
                "permitted_role": self.permitted_role,
                "intended_episode_id": None if self.intended_episode_id is None else self.intended_episode_id.value,
            },
        )


@dataclass(frozen=True, slots=True)
class EffectiveSynthesisInput:
    job_id: NarrationJobId
    lane: Lane
    passage_id: PassageId
    text_revision: int
    text: PassageText
    recipe_id: PassageRenderRecipeId
    recipe_revision: int
    recipe_digest: ContentDigest
    compiler_version: str
    settings: EffectiveTakeSettings
    contract_digest: ContentDigest
    authority_scope: AuthorityScope
    authority_revision: int
    authority_digest: ContentDigest
    authority_observed_at: datetime
    endpoint: str
    api_schema: str
    capability_snapshot: str
    rendered_transcript: str
    rendered_transcript_byte_length: int
    rendered_transcript_digest: ContentDigest
    canonical_projection: str
    canonical_projection_digest: ContentDigest
    timestamps_requested: bool
    normalization: str
    output_audio: CanonicalAudioFacts
    billable_rule: str
    billable_characters: int
    request_digest: ContentDigest

    @classmethod
    def create(cls, **arguments: object) -> EffectiveSynthesisInput:
        rendered = _required_text(arguments.get("rendered_transcript"), "rendered transcript")
        projection = _required_text(arguments.get("canonical_projection"), "canonical projection")
        text = arguments.get("text")
        if type(text) is not PassageText or projection != text.value:
            raise ValidationError("rendered transcript projection must equal canonical PassageText")
        raw = rendered.encode("utf-8")
        if len(raw) > 16_384:
            raise ValidationError("advanced compiler output must not exceed 16,384 UTF-8 bytes")
        rendered_digest = ContentDigest.from_bytes(raw)
        projection_digest = ContentDigest.from_bytes(projection.encode("utf-8"))
        payload = cls._digest_payload(
            arguments,
            rendered_byte_length=len(raw),
            rendered_digest=rendered_digest,
            projection_digest=projection_digest,
        )
        request_digest = semantic_digest("narrator_voice.effective_synthesis_input.v1", payload)
        return cls(
            **arguments,
            rendered_transcript_byte_length=len(raw),
            rendered_transcript_digest=rendered_digest,
            canonical_projection_digest=projection_digest,
            request_digest=request_digest,
        )

    @staticmethod
    def _digest_payload(
        arguments: dict[str, object],
        *,
        rendered_byte_length: int,
        rendered_digest: ContentDigest,
        projection_digest: ContentDigest,
    ) -> dict[str, object]:
        text = arguments["text"]
        return {
            "job_id": arguments["job_id"].value,
            "lane": arguments["lane"].value,
            "passage_id": arguments["passage_id"].value,
            "text_revision": arguments["text_revision"],
            "text_digest": text.digest.hex_digest,
            "recipe_id": arguments["recipe_id"].value,
            "recipe_revision": arguments["recipe_revision"],
            "recipe_digest": arguments["recipe_digest"].hex_digest,
            "compiler_version": arguments["compiler_version"],
            "settings_digest": arguments["settings"].digest.hex_digest,
            "contract_digest": arguments["contract_digest"].hex_digest,
            "authority_scope_digest": arguments["authority_scope"].digest.hex_digest,
            "authority_revision": arguments["authority_revision"],
            "authority_digest": arguments["authority_digest"].hex_digest,
            "authority_observed_at": arguments["authority_observed_at"].isoformat(),
            "endpoint": arguments["endpoint"],
            "api_schema": arguments["api_schema"],
            "capability_snapshot": arguments["capability_snapshot"],
            "rendered_transcript_byte_length": rendered_byte_length,
            "rendered_transcript_digest": rendered_digest.hex_digest,
            "canonical_projection_digest": projection_digest.hex_digest,
            "timestamps_requested": arguments["timestamps_requested"],
            "normalization": arguments["normalization"],
            "output_audio": "wav/pcm_s16le/16/little/1/44100",
            "billable_rule": arguments["billable_rule"],
            "billable_characters": arguments["billable_characters"],
        }

    def __post_init__(self) -> None:
        if type(self.job_id) is not NarrationJobId or type(self.passage_id) is not PassageId or type(self.text) is not PassageText:
            raise ValidationError("effective input requires exact job and passage IDs")
        if type(self.lane) is not Lane:
            raise ValidationError("effective input lane is invalid")
        for field, value in (("text revision", self.text_revision), ("recipe revision", self.recipe_revision), ("authority revision", self.authority_revision)):
            if type(value) is not int or value < 1:
                raise ValidationError(f"{field} must be a positive integer")
        if type(self.recipe_id) is not PassageRenderRecipeId or type(self.recipe_digest) is not ContentDigest:
            raise ValidationError("effective input recipe binding is invalid")
        if type(self.settings) is not EffectiveTakeSettings or type(self.contract_digest) is not ContentDigest:
            raise ValidationError("effective input settings or contract binding is invalid")
        if type(self.authority_scope) is not AuthorityScope or type(self.authority_digest) is not ContentDigest:
            raise ValidationError("effective input authority binding is invalid")
        _utc(self.authority_observed_at, "authority observation time")
        if not self.authority_scope.covers(AuthorityOperation.GENERATE, self.authority_observed_at):
            raise ValidationError("effective input authority scope must cover generation when observed")
        if (
            (self.lane is Lane.B and self.authority_scope.intended_episode_id is not None)
            or (self.lane is Lane.C and self.authority_scope.intended_episode_id is None)
        ):
            raise ValidationError("effective input lane and authority episode binding must match")
        for field, value in (("compiler version", self.compiler_version), ("endpoint", self.endpoint), ("API schema", self.api_schema), ("capability snapshot", self.capability_snapshot), ("rendered transcript", self.rendered_transcript), ("canonical projection", self.canonical_projection), ("normalization", self.normalization), ("billable rule", self.billable_rule)):
            _required_text(value, field)
        if type(self.timestamps_requested) is not bool:
            raise ValidationError("timestamps_requested must be boolean")
        if type(self.output_audio) is not CanonicalAudioFacts:
            raise ValidationError("effective input requires canonical audio facts")
        if type(self.billable_characters) is not int or self.billable_characters < 0:
            raise ValidationError("billable characters must be a nonnegative integer")
        raw = self.rendered_transcript.encode("utf-8")
        if len(raw) > 16_384:
            raise ValidationError("advanced compiler output must not exceed 16,384 UTF-8 bytes")
        if self.rendered_transcript_byte_length != len(raw) or self.rendered_transcript_digest != ContentDigest.from_bytes(raw):
            raise ValidationError("rendered transcript byte facts do not match exact UTF-8 bytes")
        if self.canonical_projection != self.text.value or self.canonical_projection_digest != self.text.digest:
            raise ValidationError("canonical projection does not match PassageText")
        if type(self.request_digest) is not ContentDigest:
            raise ValidationError("effective input request_digest must be a ContentDigest")
        arguments = self.creation_arguments()
        expected = semantic_digest(
            "narrator_voice.effective_synthesis_input.v1",
            self._digest_payload(
                arguments,
                rendered_byte_length=self.rendered_transcript_byte_length,
                rendered_digest=self.rendered_transcript_digest,
                projection_digest=self.canonical_projection_digest,
            ),
        )
        if self.request_digest != expected:
            raise ValidationError("effective input request digest does not match its exact semantic facts")

    @property
    def rendered_transcript_bytes(self) -> bytes:
        return self.rendered_transcript.encode("utf-8")

    def creation_arguments(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "lane": self.lane,
            "passage_id": self.passage_id,
            "text_revision": self.text_revision,
            "text": self.text,
            "recipe_id": self.recipe_id,
            "recipe_revision": self.recipe_revision,
            "recipe_digest": self.recipe_digest,
            "compiler_version": self.compiler_version,
            "settings": self.settings,
            "contract_digest": self.contract_digest,
            "authority_scope": self.authority_scope,
            "authority_revision": self.authority_revision,
            "authority_digest": self.authority_digest,
            "authority_observed_at": self.authority_observed_at,
            "endpoint": self.endpoint,
            "api_schema": self.api_schema,
            "capability_snapshot": self.capability_snapshot,
            "rendered_transcript": self.rendered_transcript,
            "canonical_projection": self.canonical_projection,
            "timestamps_requested": self.timestamps_requested,
            "normalization": self.normalization,
            "output_audio": self.output_audio,
            "billable_rule": self.billable_rule,
            "billable_characters": self.billable_characters,
        }
