"""Marking which folded tokens are Indic, when folding does not preserve the word count.

This is the defect that made the Indic track disappear. `fold` splits on punctuation, so
`Vedanta-sutras,` becomes two tokens, and a caller that marked tokens by walking the written
words compared the two lengths, found them different, and fell back to marking everything
English. On one 3,735-word span that turned 214 diacritic words into none - and the failure
reported as a clean "0 Indic words" rather than as an error.
"""

import unittest

from scripts.transcript_accuracy import fold, folded_with_marks


class FoldedMarkTests(unittest.TestCase):
    def test_the_counts_cannot_disagree(self):
        tokens, marks = folded_with_marks("Gurudeva quoted the Vedanta-sutras, you see")
        self.assertEqual(len(tokens), len(marks))

    def test_a_hyphenated_indic_word_marks_both_of_its_tokens(self):
        # The exact shape of the bug: one word, two tokens, both of them Indic.
        tokens, marks = folded_with_marks("the V\u0113danta-s\u016btras say")
        self.assertIn("vedanta", tokens)
        self.assertIn("sutras", tokens)
        self.assertTrue(marks[tokens.index("vedanta")])
        self.assertTrue(marks[tokens.index("sutras")])

    def test_an_english_word_is_not_marked(self):
        tokens, marks = folded_with_marks("the lord said")
        self.assertEqual(marks, [False] * len(tokens))

    def test_it_agrees_token_for_token_with_folding_the_whole_string(self):
        # Reference and hypothesis must be tokenised identically or the matcher compares
        # two different texts, so this is not a nicety.
        line = ("Srila Prabhupada quoted janmady 'nvayad itaratas ca, the Vedanta-sutras, "
                "and said Krsna is the cause")
        tokens, _ = folded_with_marks(line)
        self.assertEqual(tokens, fold(line))

    def test_a_word_that_folds_away_entirely_contributes_no_token(self):
        # `fold` drops fillers; a dropped word must not leave a stray mark behind.
        tokens, marks = folded_with_marks("the lord")
        self.assertEqual(len(tokens), len(marks))
        self.assertNotIn("", tokens)
