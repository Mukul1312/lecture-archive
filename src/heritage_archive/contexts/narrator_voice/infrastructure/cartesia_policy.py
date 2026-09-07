"""Fixed Cartesia release policy from private lane identities, never authority status."""
from dataclasses import dataclass

from heritage_archive.kernel import ValidationError
from heritage_archive.platform.cartesia.contract import CARTESIA_TRANSPORT_CONTRACT

from ..application.ports import ReleasePolicyResolution
from ..domain.ids import DiaryEpisodeId
from ..domain.values import CanonicalAudioFacts, DeliveryControlDefaults, Lane, ReleaseSynthesisContract
from .cartesia_recipe import CARTESIA_ODIA_MARKUP_CAPABILITY
from .operations import LocalStudioVoiceProfile


@dataclass(frozen=True, slots=True)
class ConfiguredNarrationReleasePolicyResolver:
    lane_b: LocalStudioVoiceProfile
    lane_c: LocalStudioVoiceProfile

    def __post_init__(self):
        if type(self.lane_b) is not LocalStudioVoiceProfile or type(self.lane_c) is not LocalStudioVoiceProfile:
            raise ValidationError("Cartesia policy requires explicit private lane profiles")
        if (self.lane_b.initial_speed.value, self.lane_b.initial_volume.value, self.lane_b.initial_emotion) != ("0.90", "1.00", "calm"):
            raise ValidationError("Lane B starting defaults must match the accepted release policy")
        for name in ("voice_binding", "opaque_provider_voice_reference", "speaker_identity", "authorization_record_id"):
            if getattr(self.lane_b, name) == getattr(self.lane_c, name):
                raise ValidationError("Cartesia lane identities must remain separate")

    def resolve_lane_b_diary(self) -> ReleasePolicyResolution:
        return self._resolve(Lane.B, self.lane_b, None)

    def resolve_lane_c_intro(self, intended_episode_id: DiaryEpisodeId) -> ReleasePolicyResolution:
        if type(intended_episode_id) is not DiaryEpisodeId:
            raise ValidationError("Lane C requires an exact intended episode")
        return self._resolve(Lane.C, self.lane_c, intended_episode_id)

    @staticmethod
    def _resolve(lane, profile, episode) -> ReleasePolicyResolution:
        return ReleasePolicyResolution(
            ReleaseSynthesisContract(
                lane, "reviewed-odia-diary" if lane is Lane.B else "reviewed-odia-diary-intro",
                profile.speaker_identity, profile.voice_binding, "cartesia",
                profile.opaque_provider_voice_reference, "or", "sonic-3.6-2026-08-27",
                CARTESIA_TRANSPORT_CONTRACT.api_version, CARTESIA_ODIA_MARKUP_CAPABILITY.identity,
                profile.authorization_record_id, CanonicalAudioFacts(),
                "diary" if lane is Lane.B else "intro", episode,
            ),
            DeliveryControlDefaults(profile.initial_speed, profile.initial_volume, profile.initial_emotion, profile.dictionary_binding),
        )
