from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.transcript_accuracy import (fold, has_diacritics, load_hypothesis, recognisable,
                                         score, skeleton, strip_speaker_label)


class TokenTests(unittest.TestCase):

    def test_folding_drops_fillers_punctuation_and_diacritics(self) -> None:
        self.assertEqual(fold("Śrī-Mārkaṇḍeya, uh, uvāca!"), ["sri", "markandeya", "uvaca"])
        self.assertEqual(fold("Don't"), ["don't"])

    def test_diacritics_mark_the_sanskrit_track(self) -> None:
        self.assertTrue(has_diacritics("Kṛṣṇa"))
        self.assertFalse(has_diacritics("understand"))

    def test_romanisation_differences_are_recognisable(self) -> None:
        for reference, heard in (("sri", "shri"), ("krsna", "krishna"), ("bhagavan", "bhagawan"),
                                 ("vaisnava", "vaishnava"), ("markandeya", "markandeyo")):
            with self.subTest(f"{reference}/{heard}"):
                self.assertTrue(recognisable(reference, heard))

    def test_different_words_are_not_recognisable(self) -> None:
        for reference, heard in (("krsna", "krishnaloka"), ("sadhu", "shadow"), ("prema", "problem")):
            with self.subTest(f"{reference}/{heard}"):
                self.assertFalse(recognisable(reference, heard))

    def test_skeleton_removes_meaningless_romanisation_choices(self) -> None:
        self.assertEqual(skeleton("shri"), skeleton("sri"))
        self.assertEqual(skeleton("vaisnava"), skeleton("baisnaba"))


class ScoreTests(unittest.TestCase):

    def test_sanskrit_spelt_differently_counts_as_recognised_but_english_stays_strict(self) -> None:
        reference = ["sri", "krsna", "take", "shelter", "of", "the", "soles"]
        is_indic = [True, True, False, False, False, False, False]
        hypothesis = ["shri", "krishna", "take", "shelter", "of", "the", "souls"]
        tally = score(reference, is_indic, hypothesis)
        self.assertEqual(tally["near"], 2, "both Sanskrit words were recognisable")
        self.assertEqual(tally["indic"]["errors"], 0)
        self.assertEqual(tally["english"]["errors"], 1, "soles/souls is a different word")

    def test_missing_and_invented_words_are_counted(self) -> None:
        tally = score(["take", "shelter", "now"], [False] * 3, ["take", "shelter", "right", "now"])
        self.assertEqual(tally["inserted"], 1)
        tally = score(["take", "shelter", "now"], [False] * 3, ["take", "now"])
        self.assertEqual(tally["missing"], 1)

    def test_a_perfect_transcript_has_no_errors(self) -> None:
        words = ["take", "shelter", "of", "krsna"]
        tally = score(words, [False, False, False, True], list(words))
        self.assertEqual((tally["exact"], tally["wrong"], tally["missing"], tally["inserted"]), (4, 0, 0, 0))


class HypothesisSpanTests(unittest.TestCase):

    def _words(self, items: list[tuple[str, float]]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        with handle:
            for word, at in items:
                handle.write(json.dumps({"w": word, "s": at, "e": at + 0.3}) + "\n")
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_words_outside_the_span_and_in_unsubtitled_speech_are_dropped(self) -> None:
        path = self._words([("before", 5.0), ("kept", 12.0), ("chatter", 30.0), ("after", 60.0)])
        self.assertEqual(load_hypothesis(path, (10.0, 50.0), [[20.0, 40.0]]), ["kept"])

    def test_heard_words_inside_a_cue_are_scored_even_within_an_unsubtitled_span(self) -> None:
        # The re-timing marks long stretches of speech that no cue matched as "never
        # subtitled". A cue it could not match (a garbled song, say) has its time
        # interpolated into such a stretch. Dropping the heard words there while its
        # reference words stay would count every one of them as missing.
        path = self._words([("kept", 12.0), ("song", 21.0), ("chatter", 30.0)])
        heard = load_hypothesis(path, (10.0, 50.0), [[20.0, 40.0]], covered=[(20.5, 22.0)])
        self.assertEqual(heard, ["kept", "song"])


if __name__ == "__main__":
    unittest.main()


class DiacriticSpeakerLabelTests(unittest.TestCase):
    """A speaker's name may begin with a capital outside the ASCII range.

    The official archive writes "Śrīmad Gour Govinda Swāmī:" 212 times. `[A-Z]` matches none of
    them, so for 227 lines the label survived into scoring as a word the machine had failed to
    hear, and into forced alignment as audio to find.
    """

    def test_a_name_beginning_with_an_iast_capital_is_a_speaker_label(self):
        self.assertEqual(
            strip_speaker_label("Śrīmad Gour Govinda Swāmī: Ungrateful.").strip(),
            "Ungrateful.")

    def test_the_ascii_names_still_work(self):
        self.assertEqual(strip_speaker_label("Mr Peter: Yes, I think so.").strip(),
                         "Yes, I think so.")
        self.assertEqual(strip_speaker_label("Devotee: There's no loss.").strip(),
                         "There's no loss.")

    def test_a_lowercase_sanskrit_word_is_not_mistaken_for_a_name(self):
        # `śayyā` was caught this way by a first attempt that widened the class too far.
        self.assertIn("śayyā", strip_speaker_label("śayyā: a bed"))

    def test_a_name_spoken_mid_sentence_is_left_alone(self):
        # "They asked Kṛṣṇa: ..." is narration - the name was said aloud.
        line = "Our Vyāsadeva is... They asked Kṛṣṇa: kṛṣṇa-bhakta hao tumi"
        self.assertEqual(strip_speaker_label(line), line)

    def test_spoken_verse_that_merely_looks_like_a_label_survives(self):
        # The Melbourne reference opens a verse translation with "Śrī Mārkaṇḍeya said:" - every
        # word of which was spoken. A rule that removed it would delete real speech.
        line = "Śrī Mārkaṇḍeya said: O Lord Hari,"
        self.assertEqual(strip_speaker_label(line), line)
