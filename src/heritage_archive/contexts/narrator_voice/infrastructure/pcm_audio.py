"""Concrete exact PCM16 WAV inspection and dry assembly for Narrator Voice."""

from __future__ import annotations

from io import BytesIO
import wave

from heritage_archive.kernel import ContentDigest, ValidationError

from ..application.ports import DryAssemblyResult, DryPcmSource
from ..domain.evidence import ComponentOffset, DecodedMediaFacts, PassageOffset
from ..domain.values import CanonicalAudioFacts, ComponentRole
from .filesystem_evidence import FilesystemArtifactEvidenceVerifier


class CanonicalWavInspector:
    """Inspects only the exact WAV contract used by local narration artifacts."""

    def inspect_canonical_wav(self, payload: bytes) -> DecodedMediaFacts:
        facts, _ = _decode_canonical_wav(payload)
        return facts


class ExactPcmAssembler:
    """Concatenates verified PCM frames and explicit zero-valued sample gaps."""

    def __init__(self, artifacts: FilesystemArtifactEvidenceVerifier) -> None:
        if type(artifacts) is not FilesystemArtifactEvidenceVerifier:
            raise ValidationError("exact PCM assembler requires a filesystem artifact verifier")
        self._artifacts = artifacts

    def assemble_narration(
        self,
        sources: tuple[DryPcmSource, ...],
        gaps_samples: tuple[int, ...],
        source_offsets: tuple[PassageOffset, ...],
    ) -> DryAssemblyResult:
        _validate_narration_inputs(sources, gaps_samples, source_offsets)
        frames = []
        projected_offsets = []
        cursor = 0
        for index, (source, source_offset) in enumerate(zip(sources, source_offsets, strict=True)):
            facts, pcm = self._read_source(source)
            _validate_offset_within_source(source_offset, facts.sample_count)
            frames.append(pcm)
            projected_offsets.append(_shift_offset(source_offset, cursor))
            cursor += facts.sample_count
            if index < len(gaps_samples):
                gap = gaps_samples[index]
                frames.append(_zero_pcm_samples(gap))
                cursor += gap
        payload = _encode_canonical_wav(b"".join(frames))
        media, _ = _decode_canonical_wav(payload)
        return DryAssemblyResult(payload, media, tuple(projected_offsets), ())

    def assemble_episode(
        self,
        intro: DryPcmSource,
        diary: DryPcmSource,
        gap_samples: int,
        intro_offsets: tuple[PassageOffset, ...],
        diary_offsets: tuple[PassageOffset, ...],
        intro_snapshot_digest: ContentDigest,
        diary_snapshot_digest: ContentDigest,
    ) -> DryAssemblyResult:
        _validate_episode_inputs(
            intro,
            diary,
            gap_samples,
            intro_offsets,
            diary_offsets,
            intro_snapshot_digest,
            diary_snapshot_digest,
        )
        intro_media, intro_pcm = self._read_source(intro)
        diary_media, diary_pcm = self._read_source(diary)
        _validate_offsets_within_source(intro_offsets, intro_media.sample_count)
        _validate_offsets_within_source(diary_offsets, diary_media.sample_count)
        diary_start = intro_media.sample_count + gap_samples
        payload = _encode_canonical_wav(intro_pcm + _zero_pcm_samples(gap_samples) + diary_pcm)
        media, _ = _decode_canonical_wav(payload)
        components = (
            ComponentOffset(
                ComponentRole.INTRO,
                0,
                intro_media.sample_count,
                intro_snapshot_digest,
                tuple(_shift_offset(item, 0) for item in intro_offsets),
            ),
            ComponentOffset(
                ComponentRole.DIARY,
                diary_start,
                diary_start + diary_media.sample_count,
                diary_snapshot_digest,
                tuple(_shift_offset(item, diary_start) for item in diary_offsets),
            ),
        )
        return DryAssemblyResult(payload, media, (), components)

    def _read_source(self, source: DryPcmSource) -> tuple[DecodedMediaFacts, bytes]:
        if type(source) is not DryPcmSource:
            raise ValidationError("dry PCM source must be an exact DryPcmSource")
        payload = self._artifacts.read_verified_bytes(source.artifact)
        media, pcm = _decode_canonical_wav(payload)
        if media != source.media:
            raise ValidationError("source media facts do not match verified WAV bytes")
        return media, pcm


def _decode_canonical_wav(payload: bytes) -> tuple[DecodedMediaFacts, bytes]:
    if type(payload) is not bytes:
        raise ValidationError("canonical WAV payload must be bytes")
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise ValidationError("canonical audio must use a RIFF/WAVE container")
    try:
        with wave.open(BytesIO(payload), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            compression = source.getcomptype()
            sample_count = source.getnframes()
            frames = source.readframes(sample_count)
    except (EOFError, wave.Error) as error:
        raise ValidationError("canonical audio contains an invalid WAV container") from error
    if (channels, sample_width, sample_rate, compression) != (1, 2, 44_100, "NONE"):
        raise ValidationError("canonical audio must be PCM16 mono 44.1-kHz WAV")
    if sample_count <= 0 or len(frames) != sample_count * 2:
        raise ValidationError("canonical audio must contain complete nonempty PCM samples")
    if not any(frames):
        raise ValidationError("canonical audio cannot be all digital silence")
    return (
        DecodedMediaFacts(
            CanonicalAudioFacts(),
            sample_count,
            max(1, sample_count * 1_000 // 44_100),
            False,
        ),
        frames,
    )


def _encode_canonical_wav(pcm_frames: bytes) -> bytes:
    if type(pcm_frames) is not bytes or not pcm_frames or len(pcm_frames) % 2 != 0:
        raise ValidationError("assembled PCM frames must be nonempty complete PCM16 samples")
    output = BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(44_100)
        destination.writeframes(pcm_frames)
    return output.getvalue()


def _zero_pcm_samples(samples: int) -> bytes:
    return b"\x00\x00" * samples


def _validate_narration_inputs(
    sources: object,
    gaps_samples: object,
    source_offsets: object,
) -> None:
    if type(sources) is not tuple or not sources:
        raise ValidationError("narration assembly requires a nonempty tuple of sources")
    if type(gaps_samples) is not tuple or len(gaps_samples) != len(sources) - 1:
        raise ValidationError("narration assembly requires one gap between each source")
    if type(source_offsets) is not tuple or len(source_offsets) != len(sources):
        raise ValidationError("narration assembly requires one offset for each source")
    if any(type(source) is not DryPcmSource for source in sources):
        raise ValidationError("narration sources must be exact DryPcmSource values")
    if any(type(gap) is not int or gap < 0 for gap in gaps_samples):
        raise ValidationError("narration gaps must be nonnegative integer sample counts")
    if any(type(offset) is not PassageOffset for offset in source_offsets):
        raise ValidationError("narration source offsets must be exact PassageOffset values")


def _validate_episode_inputs(
    intro: object,
    diary: object,
    gap_samples: object,
    intro_offsets: object,
    diary_offsets: object,
    intro_snapshot_digest: object,
    diary_snapshot_digest: object,
) -> None:
    if type(intro) is not DryPcmSource or type(diary) is not DryPcmSource:
        raise ValidationError("episode assembly requires exact intro and diary sources")
    if type(gap_samples) is not int or gap_samples < 0:
        raise ValidationError("episode gap must be a nonnegative integer sample count")
    if type(intro_offsets) is not tuple or type(diary_offsets) is not tuple:
        raise ValidationError("episode passage offsets must be immutable tuples")
    if any(type(item) is not PassageOffset for item in intro_offsets + diary_offsets):
        raise ValidationError("episode passage offsets must be exact PassageOffset values")
    if type(intro_snapshot_digest) is not ContentDigest or type(diary_snapshot_digest) is not ContentDigest:
        raise ValidationError("episode snapshot digests must be exact ContentDigest values")


def _validate_offsets_within_source(offsets: tuple[PassageOffset, ...], sample_count: int) -> None:
    previous_end = 0
    for offset in offsets:
        _validate_offset_within_source(offset, sample_count)
        if offset.start_sample < previous_end:
            raise ValidationError("passage offsets must be ordered without overlap")
        previous_end = offset.end_sample


def _validate_offset_within_source(offset: PassageOffset, sample_count: int) -> None:
    if offset.start_sample < 0 or offset.end_sample > sample_count:
        raise ValidationError("passage offset must be contained within its source PCM samples")


def _shift_offset(offset: PassageOffset, start_sample: int) -> PassageOffset:
    return PassageOffset(
        offset.passage_id,
        offset.text_revision,
        offset.text_digest,
        offset.start_sample + start_sample,
        offset.end_sample + start_sample,
    )
