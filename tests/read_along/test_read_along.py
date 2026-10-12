"""What the read-along page must get right before it is worth looking at.

The page highlights word N when the aligner says word N is being spoken. That is only true if
the page's word N is the aligner's word N: the aligner numbered the words of
`spoken_words(transcript)`, while the page lays them out paragraph by paragraph with speaker
labels and editorial brackets left visible for the reader. If the two numberings drift apart by
one word, every highlight after that point is wrong and nothing on the page says so. So the
builder must refuse, loudly, rather than show it.

The other two things here are about not overclaiming: stretches of audio the transcript has no
words for must be shown as such, and an alignment nobody has checked must not look like one
somebody has.
"""

import unittest

from scripts.forced_align import spoken_words
from scripts.read_along import (check_alignment, copy_matches, disagreements, paragraphs,
                                renumber, untranscribed, verification, word_check)


def spoken(paras):
    return [text for para in paras for text, index in para if index is not None]


class ParagraphTests(unittest.TestCase):
    def test_the_spoken_tokens_are_exactly_what_the_aligner_numbered(self):
        text = ("Gour Govinda Swami: Kṛṣṇa is [verse] the Supreme Lord.\n\n"
                "Devotee: Mahārāja, [?] what is bhakti?\n"
                "Translation: It is lust only.\n")
        self.assertEqual(spoken(paragraphs(text)), spoken_words(text))

    def test_written_but_unspoken_text_stays_visible_without_a_number(self):
        paras = paragraphs("Gour Govinda Swami: Hare [verse] Kṛṣṇa")
        self.assertEqual(paras[0][0], ("Gour Govinda Swami:", None))
        self.assertEqual(paras[0][2], ("[verse]", None))
        self.assertEqual([i for _, i in paras[0] if i is not None], [0, 1])

    def test_numbering_continues_across_paragraphs(self):
        paras = paragraphs("one two\n\nthree")
        self.assertEqual(paras[1], [("three", 2)])

    def test_a_bracket_left_open_does_not_swallow_the_speech_after_it(self):
        # One editor opened "(janasya moho ’yam ahaṁ mameti" and never closed it; the rule ran on
        # to the next ")" and took 277 spoken words with it. Of 1,160 bracketed notes in the
        # archive that was the only one crossing a line, so a note now ends with its line.
        text = "(janasya moho mameti This is illusion.\nOne must give up (SB 5.5.8) the conception."
        paras = paragraphs(text)
        self.assertEqual(spoken(paras), spoken_words(text))
        self.assertIn(("illusion.", 5), paras[0])
        self.assertEqual(paras[1][4], ("(SB 5.5.8)", None))

    def test_a_verse_reference_stays_on_the_page_without_a_number(self):
        paras = paragraphs("is (SB 10.14.58) the Lord")
        self.assertEqual(paras[0], [("is", 0), ("(SB 10.14.58)", None), ("the", 1), ("Lord", 2)])

    def test_his_full_name_as_a_label_is_shown_but_not_timed(self):
        paras = paragraphs("Sri Srimad Gour Govinda Swami Maharaja: Yes.")
        self.assertEqual(paras[0], [("Sri Srimad Gour Govinda Swami Maharaja:", None), ("Yes.", 0)])

    def test_text_the_editor_says_is_not_in_the_audio_is_shown_but_not_timed(self):
        paras = paragraphs("drunken.\n\nTHE FOLLOWING IS NOT INCLUDED IN THIS AUDIO:\n\nYes, what?")
        self.assertEqual(spoken(paras), ["drunken."])
        self.assertEqual(paras[2], [("Yes, what?", None)])


class RenumberTests(unittest.TestCase):
    """Timings made before the cleanup rule changed are carried over, not thrown away.

    Re-timing every lecture takes about a day of computer time, and the landmark aligner will
    replace these timings anyway. Until then the old timings of the real words are still the
    best available - but the words now treated as notes must be dropped from them, and the page
    must say the lecture was timed with written-only text treated as speech.
    """

    def old(self, *words):
        return [{"word": w, "index": i, "start": float(i), "end": i + 0.5}
                for i, w in enumerate(words)]

    def test_words_now_treated_as_notes_are_dropped_and_the_rest_renumbered(self):
        paras = paragraphs("Sri Srimad Gour Govinda Swami Maharaja: Yes, material world.")
        old = self.old("Sri", "Srimad", "Gour", "Govinda", "Swami", "Maharaja:",
                       "Yes,", "material", "world.")
        carried, dropped = renumber(paras, old)
        self.assertEqual(dropped, 6)
        self.assertEqual([(w["word"], w["index"], w["start"]) for w in carried],
                         [("Yes,", 0, 6.0), ("material", 1, 7.0), ("world.", 2, 8.0)])
        check_alignment(paras, carried)

    def test_an_alignment_of_a_different_text_is_refused(self):
        paras = paragraphs("hare kṛṣṇa hare rāma")
        with self.assertRaises(ValueError):
            renumber(paras, self.old("one", "two", "three", "four", "five", "six"))


class AlignmentCheckTests(unittest.TestCase):
    def test_an_alignment_that_agrees_with_the_layout_passes(self):
        paras = paragraphs("hare kṛṣṇa hare")
        check_alignment(paras, [{"word": "kṛṣṇa", "index": 1, "start": 1.0, "end": 1.5}])

    def test_a_word_out_by_one_is_refused(self):
        paras = paragraphs("hare kṛṣṇa hare rāma")
        with self.assertRaises(ValueError):
            check_alignment(paras, [{"word": "rāma", "index": 2, "start": 1.0, "end": 1.5}])


class UntranscribedTests(unittest.TestCase):
    def words(self, *times):
        return [{"start": s, "end": e} for s, e in times]

    def test_head_silences_and_tail_beyond_a_real_pause_are_reported(self):
        gaps = untranscribed(self.words((30.0, 31.0), (32.0, 33.0), (60.0, 61.0)),
                             duration=200.0, max_gap=10.0)
        self.assertEqual(gaps, [(0.0, 30.0), (33.0, 60.0), (61.0, 200.0)])

    def test_an_ordinary_pause_is_not(self):
        gaps = untranscribed(self.words((1.0, 2.0), (8.0, 9.0)), duration=12.0, max_gap=10.0)
        self.assertEqual(gaps, [])


class ListeningCopyTests(unittest.TestCase):
    """The page plays a constant-bitrate copy because browsers seek the archive's VBR MP3s
    4-9 s short while reporting the time asked for. A copy whose length differs from the
    recording the aligner timed would trade that error for another, so it is not used."""

    def test_a_copy_the_same_length_as_the_timed_recording_is_used(self):
        self.assertTrue(copy_matches(3649.016054, 3649.016054421769))

    def test_a_copy_that_is_longer_or_shorter_is_not(self):
        self.assertFalse(copy_matches(3649.30, 3649.016))
        self.assertFalse(copy_matches(None, 3649.016))


class WordCheckTests(unittest.TestCase):
    """Where the aligner and a recogniser disagree about when a word was said.

    The placement check cannot see this: a verified lecture had English words laid 140-206 s
    early over a chanted verse the transcript omits, and passed. Comparing word times can see
    it, provided a common word is never paired with another occurrence of itself far away -
    which is why only runs of several consecutive words count.
    """

    def aligned(self, *triples):
        return [{"word": w, "index": i, "start": s, "end": s + 0.3}
                for i, (w, s) in enumerate(triples)]

    def heard(self, *pairs):
        return [{"w": w, "s": s, "e": s + 0.3} for w, s in pairs]

    def test_words_placed_where_they_were_heard_agree(self):
        offsets = word_check(self.aligned(("the", 1.0), ("holy", 1.4), ("name", 1.8)),
                             self.heard(("the", 1.02), ("holy", 1.41), ("name", 1.79)))
        self.assertTrue(all(abs(o) < 0.05 for o in offsets.values()))
        self.assertEqual(set(offsets), {0, 1, 2})

    def test_a_run_laid_early_shows_its_offset(self):
        offsets = word_check(self.aligned(("much", 361.1), ("humbler", 361.5), ("than", 361.9)),
                             self.heard(("much", 513.5), ("humbler", 513.9), ("than", 514.3)))
        self.assertAlmostEqual(offsets[0], -152.4, places=1)

    def test_a_lone_common_word_is_never_paired(self):
        # `ei` was once paired with an occurrence 25 s away. One word is not evidence.
        offsets = word_check(self.aligned(("ei", 10.0), ("x", 11.0)),
                             self.heard(("y", 30.0), ("ei", 35.0)))
        self.assertEqual(offsets, {})

    def test_neighbouring_disagreements_become_one_region(self):
        words = self.aligned(*[(f"w{i}", 100.0 + i) for i in range(6)])
        offsets = {i: -150.0 for i in range(6)}
        self.assertEqual(disagreements(words, offsets), [[100.0, 105.3, 6]])

    def test_a_stray_disagreeing_word_is_not_a_region(self):
        words = self.aligned(("a", 1.0), ("b", 2.0), ("c", 3.0))
        self.assertEqual(disagreements(words, {0: 0.0, 1: 4.0, 2: 0.0}), [])


class VerificationTests(unittest.TestCase):
    comparison = {
        "lectures": [{"slug": "good", "systems": {
            "elevenlabs": {"span_error": 0.10, "whole_file_error": 0.09},
            "sarvam": {"span_error": 0.16, "whole_file_error": 0.15}}}],
        "excluded": [{"slug": "bad", "ratios": {"elevenlabs": 5.64, "sarvam": 2.11}}],
    }

    def test_a_lecture_that_passed_the_placement_check_is_verified(self):
        self.assertEqual(verification("good", self.comparison)["status"], "verified")

    def test_a_lecture_that_failed_it_says_so(self):
        result = verification("bad", self.comparison)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["worst_ratio"], 5.64)

    def test_a_lecture_nobody_checked_is_unverified_not_good(self):
        self.assertEqual(verification("never-read", self.comparison)["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
