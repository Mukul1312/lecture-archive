"""Turning the printed transcript into something a CTC aligner can be asked to find.

Forced alignment answers a different question from recognition: the words are already known,
and we want to know *when* each one was said. That is what makes read-along possible for
`flex`, which emits 6,175 words and not one timestamp.

The alignment model is torchaudio's MMS_FA, whose whole alphabet is 26 latin letters, an
apostrophe and a star. Our transcript is romanised Sanskrit and Bengali with IAST diacritics,
so everything here is about getting that text into those 29 symbols without lying about what
was spoken. A wrong token stream does not fail loudly - it silently slides every later word.
"""

import unittest

from scripts.forced_align import DICTIONARY, romanise, spoken_words, tokenise


class RomanisingTests(unittest.TestCase):
    def test_iast_diacritics_fold_into_the_plain_alphabet(self):
        self.assertEqual(romanise("aṅghri-mūlaṁ"), "anghrimulam")
        self.assertEqual(romanise("śaraṇaṁ"), "saranam")

    def test_every_romanised_character_exists_in_the_model_alphabet(self):
        for word in ("prapanno", "'smy", "aṅghri-mūlaṁ", "jñāna-kāśayā", "Kṛṣṇa", "don't"):
            for ch in romanise(word):
                self.assertIn(ch, DICTIONARY, f"{ch!r} from {word!r} is not alignable")

    def test_the_hyphen_is_removed_rather_than_kept(self):
        # '-' is the BLANK symbol at index 0. Emitting it as a target would ask CTC to align
        # a blank, which is not a thing the algorithm allows.
        self.assertNotIn("-", romanise("aṅghri-mūlaṁ"))
        self.assertEqual(DICTIONARY["-"], 0, "blank must stay at index 0")

    def test_the_avagraha_is_dropped_because_it_is_not_a_sound(self):
        # In "prapanno 'smy" the apostrophe marks an elided initial a. Nobody says it, so
        # asking the aligner to find it would consume audio that belongs to the next letter.
        self.assertEqual(romanise("'smy"), "smy")

    def test_an_apostrophe_inside_a_word_is_kept_because_it_is_in_the_alphabet(self):
        self.assertEqual(romanise("don't"), "don't")

    def test_case_and_punctuation_do_not_survive(self):
        self.assertEqual(romanise("Kṛṣṇa,"), "krsna")
        self.assertEqual(romanise("(Translation)"), "translation")


class ApostropheTests(unittest.TestCase):
    """This reference uses U+2019 only for avagraha and U+0027 only for contractions, but that
    is its habit and not a rule, so both marks must obey the same rule."""

    def test_a_curly_avagraha_is_dropped_like_a_straight_one(self):
        self.assertEqual(romanise("’smy"), romanise("'smy"))

    def test_a_curly_contraction_keeps_its_apostrophe(self):
        self.assertEqual(romanise("isn’t"), "isn't")

    def test_a_possessive_apostrophe_is_not_a_sound(self):
        self.assertEqual(romanise("devotees'"), "devotees")


class SpeakerLabelTests(unittest.TestCase):
    """Forced alignment cannot decline a word. A label left in the text is found anyway, in
    audio belonging to its neighbours, which are then placed wrongly too."""

    def test_the_name_of_the_speaker_is_not_treated_as_speech(self):
        self.assertEqual(spoken_words("Gour Govinda Swami: And therefore you fear?"),
                         ["And", "therefore", "you", "fear?"])

    def test_a_line_without_a_label_is_left_alone(self):
        self.assertEqual(spoken_words("prapanno ’smy aṅghri-mūlaṁ te"),
                         ["prapanno", "’smy", "aṅghri-mūlaṁ", "te"])


class WrittenOnlyTests(unittest.TestCase):
    """Writing that is a note to the reader, which the aligner must never look for in the audio.

    Each of these was found in the archive's transcripts being timed as speech.
    """

    def test_a_reference_in_round_brackets_is_not_speech(self):
        # The scorer has always dropped these; the aligner did not, so the two disagreed about
        # what was said. "(Bhagavad-gītā 4.7)" stays on the page, but nobody says it.
        self.assertEqual(spoken_words("dharmasya glānir bhavati (Bhagavad-gītā 4.7) yes"),
                         ["dharmasya", "glānir", "bhavati", "yes"])

    def test_a_bracket_left_open_takes_only_its_own_line(self):
        from scripts.transcript_accuracy import fold, normalise
        text = "(janasya moho mameti This is illusion.\nOne must (SB 5.5.8) give up."
        self.assertEqual(spoken_words(text)[-3:], ["must", "give", "up."])
        self.assertEqual(spoken_words(text)[5], "illusion.")
        self.assertEqual(fold(" ".join(spoken_words(text))), fold(normalise(text)))

    def test_a_footnote_line_is_not_speech(self):
        self.assertEqual(spoken_words("material world?\n* Cc M 19.151\nOh, in the material world."),
                         ["material", "world?", "Oh,", "in", "the", "material", "world."])

    def test_a_literal_asterisk_never_reaches_the_aligner(self):
        # A word that IS "*" is the aligner's wildcard. Five arrived from footnote markers.
        self.assertNotIn("*", spoken_words("one * two\n*\nthree"))

    def test_text_the_editor_says_is_not_in_the_audio_is_not_speech(self):
        text = "Don't be drunken.\n\nTHE FOLLOWING IS NOT INCLUDED IN THIS AUDIO:\n\nYes, what?\n"
        self.assertEqual(spoken_words(text), ["Don't", "be", "drunken."])

    def test_the_aligner_and_the_scorer_agree_on_what_was_said(self):
        from scripts.transcript_accuracy import fold, normalise
        text = ("Sri Srimad Gour Govinda Swami Maharaja: So how it will be here?\n"
                "Devotee: Kṛṣṇa [verse] is (SB 10.14.58) the Lord\n"
                "* see SB 10.14.58\n"
                "They asked Kṛṣṇa: bhakta hao tumi\n"
                "THE FOLLOWING IS NOT INCLUDED IN THIS AUDIO:\nYes, what do you say\n")
        self.assertEqual(fold(" ".join(spoken_words(text))), fold(normalise(text)))


class TokenisingTests(unittest.TestCase):
    def test_each_target_knows_which_word_it_came_from(self):
        # This mapping is the whole game: spans come back per token and must be folded back
        # onto words. An off-by-one here shifts the highlight for the rest of the lecture.
        t = tokenise(["hare", "krsna"])
        self.assertEqual(len(t.targets), len(t.owner))
        self.assertEqual(t.owner, [0, 0, 0, 0, 1, 1, 1, 1, 1])

    def test_targets_are_dictionary_indices(self):
        t = tokenise(["ab"])
        self.assertEqual(t.targets, [DICTIONARY["a"], DICTIONARY["b"]])

    def test_no_target_is_ever_the_blank_symbol(self):
        t = tokenise(["aṅghri-mūlaṁ", "'smy", "SB", "12.10.2", "hare"])
        self.assertNotIn(0, t.targets)

    def test_a_word_with_nothing_alignable_is_reported_not_swallowed(self):
        # "12.10.2" has no letters. Dropping it quietly would be fine for the token stream but
        # would leave the caller believing it has a span for every word.
        t = tokenise(["hare", "12.10.2", "krsna"])
        self.assertEqual(t.skipped, [1])
        self.assertNotIn(1, t.owner)

    def test_words_that_survive_keep_their_original_position(self):
        t = tokenise(["hare", "12.10.2", "krsna"])
        self.assertEqual(sorted(set(t.owner)), [0, 2])

    def test_an_empty_transcript_produces_no_targets(self):
        t = tokenise([])
        self.assertEqual(t.targets, [])
        self.assertEqual(t.owner, [])


if __name__ == "__main__":
    unittest.main()
