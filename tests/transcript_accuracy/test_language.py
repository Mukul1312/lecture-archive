"""Telling Sanskrit from Bengali in the reference.

Every "Sanskrit" figure in this project was really Sanskrit AND Bengali, because the scorer's
Indic track is "any word written with diacritics" and Bengali transliteration carries just as
many. That hid a routing result: 676 Indic words are 486 Sanskrit and 190 Bengali, and
different systems are best at each. Deepgram gets 100% of the Bengali wrong.
"""

import unittest

from scripts.transcript_accuracy import indic_language

SANSKRIT = [
    "sarva-dharmān parityajya, mām ekaṁ śaraṇaṁ vraja",
    "bhayaṁ dvitīyābhiniveśataḥ syād",
    "nidrayā hriyate naktaṁ, vyavāyena ca vā vayaḥ",
    "prapanno ’smy aṅghri-mūlaṁ te prapannābhaya-daṁ hare",
]
BENGALI = [
    "bhuliyā tomāre, saṁsāre āsiyā, peye nānā-vidha byathā",
    "jananī jaṭhare, chilāma jakhona, biṣama bandhana-pāśe",
    "eka-bāra prabhu! dekhā diyā more, vañcile e dīna dāse",
    "kali-yuge nāma-sange kṛṣṇa-avatāra nāma haite haya sarva-jagat-nistāra",
]


class LanguageTests(unittest.TestCase):
    def test_sanskrit_scripture_is_recognised(self):
        for line in SANSKRIT:
            with self.subTest(line=line[:36]):
                self.assertEqual(indic_language(line), "sanskrit")

    def test_bengali_padavali_is_recognised(self):
        # These are the lines the archive loses entirely; calling them Sanskrit sent them to
        # the wrong recogniser and buried the failure in a column labelled Sanskrit.
        for line in BENGALI:
            with self.subTest(line=line[:36]):
                self.assertEqual(indic_language(line), "bengali")

    def test_the_bengali_verb_endings_are_what_decide_it(self):
        self.assertEqual(indic_language("bhuliyā āsiyā kariyā"), "bengali")

    def test_bengali_pronouns_decide_it_too(self):
        self.assertEqual(indic_language("āmi tomāre more"), "bengali")

    def test_plain_english_is_not_called_indic(self):
        self.assertEqual(indic_language("do you understand mr peter"), "sanskrit")

    def test_an_empty_line_does_not_raise(self):
        self.assertIn(indic_language(""), ("sanskrit", "bengali"))


if __name__ == "__main__":
    unittest.main()
