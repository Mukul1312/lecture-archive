"""Focused tests for the concrete canonical-WAV adapter and dry PCM assembly."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
import wave


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ArtifactId, ValidationError
from heritage_archive.contexts.narrator_voice.application.ports import DryPcmSource
from heritage_archive.contexts.narrator_voice.domain.evidence import PassageOffset
from heritage_archive.contexts.narrator_voice.domain.ids import PassageId
from heritage_archive.contexts.narrator_voice.domain.values import ComponentRole, SafeRelativeArtifactPath
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier,
    FilesystemArtifactStore,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import (
    CanonicalWavInspector,
    ExactPcmAssembler,
)
from tests.heritage_archive.narrator_voice.fixtures import NOW, digest, uuid


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CanonicalPcmAudioTests(unittest.TestCase):
    def test_inspector_accepts_only_non_silent_pcm16_mono_44k1_riff_wave(self) -> None:
        inspector = CanonicalWavInspector()
        payload = _wav(b"\x01\x00\x02\x00")

        facts = inspector.inspect_canonical_wav(payload)

        self.assertEqual((facts.sample_count, facts.duration_ms, facts.all_digital_silence), (2, 1, False))
        for malformed in (
            _wav(b"\x01\x00", sample_rate=48_000),
            _wav(b"\x01\x00\x02\x00", channels=2),
            _wav(b"\x01", sample_width=1),
            payload[:20] + b"\x06\x00" + payload[22:],
            b"RIFX" + payload[4:],
        ):
            with self.subTest(malformed=malformed[:12]):
                with self.assertRaises(ValidationError):
                    inspector.inspect_canonical_wav(malformed)

    def test_inspector_rejects_empty_or_all_zero_pcm(self) -> None:
        inspector = CanonicalWavInspector()
        for payload in (_wav(b""), _wav(b"\x00\x00\x00\x00")):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    inspector.inspect_canonical_wav(payload)

    def test_narration_assembly_concatenates_exact_frames_and_projects_offsets(self) -> None:
        first_pcm = b"\x01\x00\x02\x00"
        second_pcm = b"\x03\x00\x04\x00\x05\x00"
        with self._root() as root:
            assembler = ExactPcmAssembler(FilesystemArtifactEvidenceVerifier(root))
            first = self._source(root, 401, "takes/first.wav", first_pcm)
            second = self._source(root, 402, "takes/second.wav", second_pcm)
            first_offset = _offset(410, 0, 2)
            second_offset = _offset(411, 1, 3)

            result = assembler.assemble_narration((first, second), (2,), (first_offset, second_offset))

            self.assertEqual(_frames(result.canonical_wav_bytes), first_pcm + b"\x00\x00\x00\x00" + second_pcm)
            self.assertEqual(result.media.sample_count, 7)
            self.assertEqual(
                tuple((item.passage_id, item.start_sample, item.end_sample) for item in result.passage_offsets),
                ((first_offset.passage_id, 0, 2), (second_offset.passage_id, 5, 7)),
            )

    def test_episode_assembly_projects_intro_and_diary_offsets_at_exact_samples(self) -> None:
        intro_pcm = b"\x01\x00\x02\x00"
        diary_pcm = b"\x03\x00\x04\x00\x05\x00"
        with self._root() as root:
            assembler = ExactPcmAssembler(FilesystemArtifactEvidenceVerifier(root))
            intro = self._source(root, 420, "masters/intro.wav", intro_pcm)
            diary = self._source(root, 421, "masters/diary.wav", diary_pcm)
            intro_digest, diary_digest = digest("intro"), digest("diary")

            result = assembler.assemble_episode(
                intro, diary, 2, (_offset(422, 0, 2),), (_offset(423, 1, 3),), intro_digest, diary_digest
            )

            self.assertEqual(_frames(result.canonical_wav_bytes), intro_pcm + b"\x00\x00\x00\x00" + diary_pcm)
            self.assertEqual(
                tuple((item.role, item.start_sample, item.end_sample) for item in result.component_offsets),
                ((ComponentRole.INTRO, 0, 2), (ComponentRole.DIARY, 4, 7)),
            )
            self.assertEqual(
                tuple((item.start_sample, item.end_sample) for item in result.component_offsets[1].passage_offsets),
                ((5, 7),),
            )

    def test_assembler_refuses_bad_counts_or_media_that_disagrees_with_bytes(self) -> None:
        with self._root() as root:
            source = self._source(root, 430, "takes/source.wav", b"\x01\x00\x02\x00")
            assembler = ExactPcmAssembler(FilesystemArtifactEvidenceVerifier(root))
            offset = _offset(431, 0, 2)
            with self.assertRaises(ValidationError):
                assembler.assemble_narration((source,), (1,), (offset,))
            with self.assertRaises(ValidationError):
                assembler.assemble_narration((source,), (), (_offset(432, 0, 3),))

    def _root(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = LocalNarrationRoot.open(Path(temporary_directory.name), (PROJECT_ROOT,))
        root.initialize_layout()
        return _RootContext(root)

    @staticmethod
    def _source(root: LocalNarrationRoot, index: int, location: str, pcm: bytes) -> DryPcmSource:
        publication = FilesystemArtifactStore(root, _Identifier([ArtifactId(uuid(index))])).publish(
            SafeRelativeArtifactPath(location), _wav(pcm), "audio/wav", NOW
        )
        media = CanonicalWavInspector().inspect_canonical_wav(_wav(pcm))
        return DryPcmSource(publication, media)


class _Identifier:
    def __init__(self, values):
        self._values = list(values)

    def new_id(self, kind):
        return self._values.pop(0)


class _RootContext:
    def __init__(self, root: LocalNarrationRoot) -> None:
        self._root = root

    def __enter__(self) -> LocalNarrationRoot:
        return self._root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def _wav(pcm: bytes, *, channels: int = 1, sample_width: int = 2, sample_rate: int = 44_100) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return buffer.getvalue()


def _frames(payload: bytes) -> bytes:
    with wave.open(BytesIO(payload), "rb") as source:
        return source.readframes(source.getnframes())


def _offset(index: int, start: int, end: int) -> PassageOffset:
    return PassageOffset(PassageId(uuid(index)), 1, digest(f"passage-{index}"), start, end)


if __name__ == "__main__":
    unittest.main()
