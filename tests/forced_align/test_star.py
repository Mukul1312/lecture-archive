"""Audio the transcript does not account for.

The Melbourne reference is a caption file: every second of speech has text against it. The
official archive's transcripts are published prose - edited, and with questioner turns largely
left out - so the recording contains speech the text never mentions.

Forced alignment cannot decline a word, and it must consume every frame. Given audio it has no
text for, it does the only thing it can: it stretches the surrounding words across the gap. The
words are then all placed wrongly and nothing reports it.

The star is the escape. MMS_FA carries a wildcard symbol that matches anything, so a `*` in the
word list says "there may be speech here that I have not given you words for". The caller places
them, because only the caller knows where its text might be incomplete.
"""

import unittest

import torch

from scripts.forced_align import DICTIONARY, STAR, align, tokenise

from tests.forced_align.test_spans import posteriors


class StarTokenisingTests(unittest.TestCase):
    def test_a_star_becomes_the_wildcard_target(self):
        flat = tokenise([STAR])
        self.assertEqual(flat.targets, [DICTIONARY[STAR]])

    def test_a_star_is_not_mistaken_for_a_word_with_no_letters(self):
        # Without this it would land in `skipped`, and the caller would be told its gap marker
        # was unalignable punctuation.
        self.assertEqual(tokenise([STAR]).skipped, [])

    def test_ordinary_words_keep_their_own_targets_around_a_star(self):
        flat = tokenise(["ab", STAR, "cd"])
        self.assertEqual(flat.owner, [0, 0, 1, 2, 2])
        self.assertEqual(flat.targets[2], DICTIONARY[STAR])

    def test_a_star_inside_a_word_is_still_not_a_sound(self):
        # Only a word that IS a star marks a gap; an asterisk in text is punctuation.
        self.assertEqual(tokenise(["ab*cd"]).targets,
                         [DICTIONARY[c] for c in "abcd"])


class StarAlignmentTests(unittest.TestCase):
    def test_a_star_absorbs_audio_no_word_accounts_for(self):
        # "ab" is spoken, then something the transcript never mentions, then "cd".
        spans = align(posteriors("ab" + "q" * 10 + "cd"), ["ab", STAR, "cd"])
        words = {s.word: s for s in spans}
        self.assertIn(STAR, words)
        self.assertGreater(words[STAR].end - words[STAR].start, 5,
                           "the star should be holding the unaccounted-for frames")

    def test_a_gap_is_reported_rather_than_swallowed_by_the_blank(self):
        """The star's real worth on this corpus: it makes the gap *visible*.

        CTC's blank already absorbs audio no target accounts for, so the neighbouring words are
        not necessarily dragged across it - measured here, "ab" is two frames either way. What
        blank cannot do is tell anyone it happened. A star comes back as a span, so a transcript
        that omits a questioner's turn leaves a mark that can be counted and inspected instead
        of a silence that looks like success.
        """
        frames = "ab" + "q" * 10 + "cd"
        with_star = align(posteriors(frames), ["ab", STAR, "cd"])
        without = align(posteriors(frames), ["ab", "cd"])

        self.assertEqual(len(without), 2, "blank hid the gap entirely, which is the point")
        star = next(s for s in with_star if s.word == STAR)
        self.assertGreater(star.end - star.start, 5)
        # And the words on either side are no worse off for it.
        named = {s.word: s for s in with_star}
        plain = {s.word: s for s in without}
        for word in ("ab", "cd"):
            self.assertLessEqual(named[word].end - named[word].start,
                                 plain[word].end - plain[word].start)

    def test_a_star_reports_where_the_unaccounted_audio_was(self):
        spans = align(posteriors("ab" + "q" * 10 + "cd"), ["ab", STAR, "cd"])
        star = next(s for s in spans if s.word == STAR)
        self.assertGreaterEqual(star.start, 0)
        self.assertLessEqual(star.end, 14)

    def test_a_transcript_that_begins_late_can_say_so(self):
        spans = align(posteriors("q" * 8 + "abcd"), [STAR, "abcd"])
        word = next(s for s in spans if s.word == "abcd")
        self.assertGreater(word.start, 3, "the opening speech should not have been given to 'abcd'")


if __name__ == "__main__":
    unittest.main()
