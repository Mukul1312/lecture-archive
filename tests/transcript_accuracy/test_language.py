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
# Caitanya-caritāmṛta and Caitanya-bhāgavata verses as the lectures quote them, each read by hand
# (29-30 October 2026). Every one of these but the last was called Sanskrit before: the
# narrative Bengali of these books has few of the song endings the lists were drawn from.
CARITAMRTA_BENGALI = [
    "uttama hañā āpanāke māne tṛṇādhama",                          # Cc. Antya 20.22
    "dui-prakāre sahiṣṇutā kare vṛkṣa-sama",                       # Cc. Antya 20.22
    "gharma-vṛṣṭi sahe, ānera karaye rakṣaṇa",                     # Cc. Antya 20.24
    "ei-mata hañā yei kṛṣṇa-nāma laya",                            # Cc. Antya 20.26
    "avaśya pāibe tabe śrī-kṛṣṇa-caraṇa",                          # Cc. Ādi 17.33
    "jīvera nistāra lāgi' sūtra kaila vyāsa māyāvādi-bhāṣya śunile haya sarva-nāśa",  # Madhya 6.169
    "prabhu kahe-kahilāṅ ei mahā-mantra",                          # CB Madhya 23.77
    "tāṅra doṣa nāhi, teṅho ājñā-kārī dāsa āra yei śune tāra haya sarva-nāśa",  # Cc. Ādi 7.114
]
QUOTED_SANSKRIT = [
    "kaṁ vā dayāluṁ śaraṇaṁ vrajema",                              # SB 3.2.23
    "mahājano yena gataḥ sa panthāḥ",                              # quoted at Cc. Madhya 17.186
    "jīvasya tattvajijñāsā nārtho yaśceha karmabhiḥ",              # SB 1.2.10
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

    def test_caitanya_caritamrta_bengali_is_recognised(self):
        for line in CARITAMRTA_BENGALI:
            with self.subTest(line=line[:36]):
                self.assertEqual(indic_language(line), "bengali")

    def test_sanskrit_quoted_in_a_bengali_book_stays_sanskrit(self):
        for line in QUOTED_SANSKRIT:
            with self.subTest(line=line[:36]):
                self.assertEqual(indic_language(line), "sanskrit")

    def test_a_listed_bengali_word_is_not_also_counted_as_sanskrit(self):
        # `haya` is on the Bengali list and also ends in the Sanskrit "-aya", so it used to cancel
        # itself; with `bhāṣya` read as a Sanskrit "-asya" genitive the line tied and went Sanskrit.
        self.assertEqual(indic_language("māyāvādi-bhāṣya śunile haya sarva-nāśa"), "bengali")

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
