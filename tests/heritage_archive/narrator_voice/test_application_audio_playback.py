"""Application playback uses parent-owned evidence and verified synthetic WAV bytes."""

from dataclasses import fields
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from heritage_archive.kernel import ValidationError
from heritage_archive.contexts.narrator_voice.application import commands, handlers
from heritage_archive.contexts.narrator_voice.domain.diary_episode import DiaryEpisode
from heritage_archive.contexts.narrator_voice.domain.errors import NotFound
from heritage_archive.contexts.narrator_voice.domain.evidence import ReviewAuthority, ReviewOutcome
from heritage_archive.contexts.narrator_voice.domain.ids import CommandId, DiaryEpisodeId, ReviewDecisionId
from heritage_archive.contexts.narrator_voice.domain.values import CanonicalAudioFacts, PassageText
from heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence import (
    FilesystemArtifactEvidenceVerifier, FilesystemArtifactStore,
)
from heritage_archive.contexts.narrator_voice.infrastructure.local_root import LocalNarrationRoot
from heritage_archive.contexts.narrator_voice.infrastructure.pcm_audio import (
    CanonicalWavInspector, encode_canonical_pcm16_wav,
)
from tests.heritage_archive.narrator_voice import test_application_episode as episode_fixture
from tests.heritage_archive.narrator_voice.fakes import FakeIdentifierSource
from tests.heritage_archive.narrator_voice.fixtures import NOW, uuid


class AudioPlaybackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = LocalNarrationRoot.open(Path(temporary.name), (SOURCE_ROOT.parent,))
        self.root.initialize_layout()
        root = self.root
        publication_media_type = getattr(self, "publication_media_type", "audio/wav")
        sample_delta = getattr(self, "sample_delta", 0)
        silence = getattr(self, "silence", False)
        malformed = getattr(self, "malformed", False)

        class SyntheticWavStore(FilesystemArtifactStore):
            # The fixture workflow supplies placeholder bytes; publish real synthetic
            # PCM with the same declared sample counts before aggregates record it.
            def __init__(self, ids):
                from heritage_archive.kernel import ArtifactId
                super().__init__(root, FakeIdentifierSource({ArtifactId: ids}))

            def publish(self, location, payload, media_type, published_at):
                samples = 250 if location.value == "fake/episode-master.wav" else 100
                frame = b"\x00\x00" if silence else b"\x01\x00"
                payload = b"not a WAV" if malformed else encode_canonical_pcm16_wav(
                    frame * (samples + sample_delta), CanonicalAudioFacts())
                return super().publish(location, payload, publication_media_type, published_at)

        with patch("tests.heritage_archive.narrator_voice.workflow.FakeArtifactStore", SyntheticWavStore):
            self.flow, self.episode_id, self.intro, self.diary, _, _ = (
                episode_fixture.EpisodeApplicationTests().assembled_and_listened()
            )
        self.job = self.flow.jobs.load(self.diary.issuing_job_id)
        episode = self.flow.episodes.load(self.episode_id)
        self.reader = FilesystemArtifactEvidenceVerifier(root)
        self.inspector = CanonicalWavInspector()
        self.cases = (
            ("ReadTakeAudio", self.flow.jobs, self.job.job_id, self.job.takes[0].take_id, self.job.takes[0]),
            ("ReadNarrationMasterAudio", self.flow.jobs, self.job.job_id, self.job.masters[0].master_id, self.job.masters[0]),
            ("ReadEpisodeMasterAudio", self.flow.episodes, self.episode_id, episode.speech_masters[0].master_id, episode.speech_masters[0]),
        )

    def read(self, case, *, parent=None, reader=None, inspector=None):
        name, repository, parent_id, child_id, _ = case
        handler = getattr(handlers, name + "Handler", None)
        self.assertIsNotNone(handler, "missing application playback handler: " + name)
        command = getattr(commands, name + "Command")(CommandId(uuid(1700)), parent or parent_id, child_id)
        self.assertEqual(len(fields(command)), 3)
        self.assertTrue(type(command).__dataclass_params__.frozen)
        return handler(repository, reader or self.reader, inspector or self.inspector)(command)

    def test_all_three_reads_return_only_exact_verified_audio_and_opaque_metadata(self):
        for case in self.cases:
            with self.subTest(kind=case[0]):
                before = case[1].load(case[2]).to_snapshot()
                result = self.read(case)
                self.assertEqual({field.name for field in fields(result)}, {
                    "command_id", "content_digest", "byte_size", "media_type", "payload",
                })
                self.assertTrue(type(result).__dataclass_params__.frozen)
                expected = encode_canonical_pcm16_wav(
                    b"\x01\x00" * (250 if case[0] == "ReadEpisodeMasterAudio" else 100), CanonicalAudioFacts(),
                )
                self.assertEqual(result.payload, expected)
                self.assertEqual(result.command_id, CommandId(uuid(1700)))
                self.assertEqual(result.content_digest, case[4].artifact.reference.content_digest)
                self.assertEqual((result.byte_size, result.media_type), (len(expected), "audio/wav"))
                self.assertEqual(case[1].load(case[2]).to_snapshot(), before)

    def test_existing_child_under_wrong_parent_and_missing_parent_are_not_found(self):
        other_episode = DiaryEpisode.prepare(DiaryEpisodeId(uuid(1701)), NOW)
        self.flow.episodes.save(other_episode, None)
        for case in self.cases:
            with self.subTest(kind=case[0]):
                other_parent = other_episode.episode_id if case[0] == "ReadEpisodeMasterAudio" else self.intro.issuing_job_id
                for parent in (other_parent, type(case[2])(uuid(1702))):
                    with self.assertRaises(NotFound):
                        self.read(case, parent=parent)

    def test_historical_rejected_take_plays_without_current_generation_authority(self):
        revision = self.job.revision
        self.job.record_review_decision(ReviewDecisionId(uuid(1703)), self.job.takes[0].take_id,
            self.flow.actor, ReviewAuthority.OPERATIONAL, ReviewOutcome.REJECTED, "fixture rejection", NOW + timedelta(seconds=1),
            expected_revision=self.job.revision)
        self.job.revise_passage_text(self.job.passages[0].passage_id, PassageText("new fixture text"), NOW + timedelta(seconds=2),
            expected_revision=self.job.revision)
        self.flow.jobs.save(self.job, revision)
        self.flow.authorizations.values.clear()
        for case in self.cases:
            with self.subTest(kind=case[0]):
                self.assertGreater(len(self.read(case).payload), 0)

    def assert_closed(self, case, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            self.read(case, **kwargs)
        self.assertNotIn(str(self.root.artifacts), str(caught.exception))
        self.assertNotIn(case[4].artifact.relative_location.value, str(caught.exception))

    def test_missing_tampered_and_reparse_artifacts_fail_closed_for_every_handler(self):
        for case in self.cases:
            publication = case[4].artifact
            path = self.root.artifacts / publication.relative_location.value
            original = path.read_bytes()
            for fault in ("missing", "tampered", "reparse_leaf", "reparse_parent"):
                with self.subTest(kind=case[0], fault=fault):
                    if fault == "missing":
                        path.unlink()
                        self.assert_closed(case)
                        path.write_bytes(original)
                    elif fault == "tampered":
                        path.write_bytes(original[:-1] + b"\xff")
                        self.assert_closed(case)
                        path.write_bytes(original)
                    else:
                        target = path if fault == "reparse_leaf" else path.parent
                        with patch("heritage_archive.contexts.narrator_voice.infrastructure.filesystem_evidence._is_reparse_point",
                            side_effect=lambda candidate: candidate == target):
                            self.assert_closed(case)

    def test_handler_checks_reader_payload_digest_and_length(self):
        class FaultyReader:
            def __init__(self, payload):
                self.payload = payload

            def read_verified_bytes(self, publication):
                return self.payload

        for case in self.cases:
            payload = self.reader.read_verified_bytes(case[4].artifact)
            for bad in (payload[:-1] + b"\xff", payload + b"extra", bytearray(payload)):
                with self.subTest(kind=case[0], payload_type=type(bad), length=len(bad)):
                    self.assert_closed(case, reader=FaultyReader(bad))

    def test_reader_and_inspector_failures_do_not_disclose_storage_paths(self):
        for case in self.cases:
            for dependency, method in (("reader", "read_verified_bytes"), ("inspector", "inspect_canonical_wav")):
                for error_type in (ValidationError, OSError):
                    with self.subTest(kind=case[0], dependency=dependency, error=error_type):
                        with patch.object(getattr(self, dependency), method,
                            side_effect=error_type(str(self.root.artifacts / case[4].artifact.relative_location.value))):
                            self.assert_closed(case)

    def test_non_wav_publications_fail_even_when_bytes_are_valid_canonical_wav(self):
        self.publication_media_type = "audio/mpeg"
        self.setUp()
        for case in self.cases:
            with self.subTest(kind=case[0]):
                self.assert_closed(case)

    def test_invalid_wav_and_decoded_sample_or_silence_mismatch_fail(self):
        for option in ("malformed", "sample_delta", "silence"):
            self.malformed = self.silence = False
            self.sample_delta = 0
            setattr(self, option, 1 if option == "sample_delta" else True)
            self.setUp()
            for case in self.cases:
                with self.subTest(kind=case[0], fault=option):
                    self.assert_closed(case)
