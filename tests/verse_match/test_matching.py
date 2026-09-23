"""Finding the printed verse behind a garbled recognition.

Speech recognition cannot read chanted Sanskrit — Whisper has zero hours of it, and models
fine-tuned on Sanskrit prose still score 99-110% WER on chant. But the verses are quotations
with fixed printed text, so the job is to recognise *which* verse, not to transcribe it.
Published prior art reaches 100% verse retrieval from a 10.1%-WER transcript this way.
"""

import unittest

from scripts.verse_match import VerseIndex, skeleton

# The real thing, as the reference writes it, and as three recognisers actually heard it.
VERSE = "prapanno 'smy aṅghri-mūlaṁ te prapannābhaya-daṁ hare"
HEARD = "upaja prapanna asmiyangri malam ti prapanna bhaya dum hari"
OTHER = "sarva-dharmān parityajya mām ekaṁ śaraṇaṁ vraja"


class SkeletonTests(unittest.TestCase):
    def test_diacritics_are_folded_away(self):
        self.assertEqual(skeleton("aṅghri-mūlaṁ"), skeleton("anghri mulam"))

    def test_the_confusions_a_recogniser_makes_are_folded(self):
        # Aspirates, sibilants, v/b and long vowels are what garbling actually does.
        self.assertEqual(skeleton("bhaya"), skeleton("baya"))
        self.assertEqual(skeleton("śaraṇaṁ"), skeleton("sharanam"))
        self.assertEqual(skeleton("vraja"), skeleton("braja"))

    def test_word_boundaries_do_not_matter(self):
        # Sandhi fuses words, so a recogniser's spacing is not evidence of anything.
        self.assertEqual(skeleton("jñāna-kāśayā"), skeleton("jnana kasaya"))

    def test_different_verses_do_not_collapse_together(self):
        self.assertNotEqual(skeleton(VERSE), skeleton(OTHER))


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.index = VerseIndex([VERSE, OTHER, "yan-māyayāpi vibudhā muhyanti jñāna-kāśayā"])

    def test_the_exact_verse_finds_itself(self):
        self.assertEqual(self.index.find(VERSE).verse, VERSE)

    def test_a_badly_garbled_recognition_still_finds_its_verse(self):
        found = self.index.find(HEARD)
        self.assertIsNotNone(found)
        self.assertEqual(found.verse, VERSE)

    def test_unrelated_speech_is_refused_rather_than_matched(self):
        # Saying "unclear" beats emitting a plausible wrong verse of scripture.
        self.assertIsNone(self.index.find("do you understand mr peter these materialistic persons"))

    def test_nothing_matches_nothing(self):
        self.assertIsNone(self.index.find(""))

    def test_a_match_reports_how_far_ahead_of_the_runner_up_it_was(self):
        found = self.index.find(HEARD)
        self.assertGreater(found.score, 0.0)
        self.assertGreaterEqual(found.margin, 0.0)

    def test_a_demanding_margin_refuses_a_close_call(self):
        self.assertIsNone(self.index.find(HEARD, min_margin=0.99))

    def test_an_empty_index_refuses_everything(self):
        self.assertIsNone(VerseIndex([]).find(VERSE))


if __name__ == "__main__":
    unittest.main()
