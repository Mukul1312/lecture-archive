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

    def test_a_margin_no_match_can_reach_refuses_everything(self):
        # A margin above 1.0 is unreachable by construction, so this proves the gate is
        # consulted at all rather than testing a particular corpus's scores.
        self.assertIsNone(self.index.find(HEARD, min_margin=1.01))

    def test_an_empty_index_refuses_everything(self):
        self.assertIsNone(VerseIndex([]).find(VERSE))



class PassageIdentityTests(unittest.TestCase):
    """The margin must compare the winner with a DIFFERENT passage.

    A real corpus is indexed as overlapping windows, so the second-ranked candidate is
    usually the same passage at another length. Both score 1.0 by containment, the margin
    reads 0.0, and abstention refuses everything. Measured on the 84,075-window KKSongs
    corpus this took Bengali coverage from 67% down to 13% — the ranking was always right,
    the confidence measure was not.
    """

    # Two windows over one song, then a different song entirely.
    WINDOWS = ["bhuliyā tomāre, saṁsāre āsiyā",
               "bhuliyā tomāre, saṁsāre āsiyā, peye nānā-vidha byathā",
               "jaya rādhā-mādhava kuñja-bihārī"]
    OWNERS = ["song-a", "song-a", "song-b"]

    def setUp(self):
        self.index = VerseIndex(self.WINDOWS, passages=self.OWNERS)

    def test_overlapping_windows_of_one_passage_do_not_cancel_the_margin(self):
        found = self.index.find("bhuliya tomare samsare asiya peye nana vidha byatha")
        self.assertIsNotNone(found, "the same passage at two lengths must not read as a tie")
        self.assertEqual(found.passage, "song-a")

    def test_a_genuinely_different_passage_still_sets_the_margin(self):
        found = self.index.find("bhuliya tomare samsare asiya peye nana vidha byatha")
        self.assertLess(found.margin, 1.01)
        self.assertGreater(found.margin, 0.0)

    def test_without_passages_two_windows_of_one_song_cancel_each_other(self):
        # Same text at the same length, so the length check cannot rescue it: without
        # passage identity the duplicate reads as a rival and the margin collapses to zero.
        # This is exactly what took Bengali coverage down to 13% on the real corpus.
        twin = ["bhuliyā tomāre, saṁsāre āsiyā, peye nānā-vidha byathā",
                "bhuliyā tomāre saṁsāre āsiyā peye nānā-vidha byathā"]
        self.assertIsNone(VerseIndex(twin).find("bhuliya tomare samsare asiya peye nana vidha byatha"))
        named = VerseIndex(twin, passages=["song-a", "song-a"])
        self.assertIsNotNone(named.find("bhuliya tomare samsare asiya peye nana vidha byatha"))

    def test_a_candidate_far_shorter_than_the_query_is_not_credible(self):
        # Containment lets a three-word window score 1.0 against a ten-word query.
        index = VerseIndex(["hare kṛṣṇa", "wholly unrelated devotional line about something else"],
                           passages=["a", "b"])
        self.assertIsNone(index.find("hare kṛṣṇa hare kṛṣṇa kṛṣṇa kṛṣṇa hare hare rāma rāma"))

    def test_the_winning_passage_is_reported(self):
        found = self.index.find("jaya radha madhava kunja bihari")
        self.assertIsNotNone(found)
        self.assertEqual(found.passage, "song-b")

if __name__ == "__main__":
    unittest.main()
