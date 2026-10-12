"""A run of quoted scripture does not contain English function words.

Reading the 26 refused runs showed **12 were never verse quotations** - names, term lists and
English fragments - and they inflated the failure count by 46%. Eight of the twelve contain an
English function word, and they contain it because of a feature I added: `gap=1` bridges one
non-diacritic word inside a run, so that `ceha` (a Sanskrit word that happens to carry no
diacritics) would stop cutting SB 1.2.10 in half. It bridges `is`, `and` and `in` just as
happily.

    Krsna is Raja Rajesvara.          <- `is` bridged
    Rupa Manjari in Krsna's           <- `in` bridged
    rajo-guna, tamo-guna, and sattva-guna.   <- `and` bridged

So the gap test is narrowed rather than a filter being bolted on afterwards: bridge a word that
could be Indic, never a word that is plainly English. This cuts both ways in our favour - the
real quotation `Srimad-Bhagavatam says, jivasya tattva jijnasa nartho yas ceha karmabhih` loses
its English lead-in and becomes the verse alone, which is a better query and a fairer thing to
score against printed text.

The remaining four are comma-delimited term lists, where **almost every word ends in a comma**.
Verse lines do not do that.
"""

import unittest

from scripts.verse_runs import indic_runs, looks_like_a_list

KRSNA = "kṛṣṇa"
NAMA = "nāma"
CINTAMANI = "cintāmaṇi"
CEHA = "ceha"                     # Sanskrit, no diacritics - the case gap=1 exists for


def aligned(tokens, step=0.6):
    return [{"word": w, "start": i * step, "end": i * step + 0.5}
            for i, w in enumerate(tokens)]


class EnglishGapTests(unittest.TestCase):
    def test_an_english_word_is_not_bridged(self):
        # `Krsna is Raja Rajesvara` must not survive as a four-word "quotation".
        found = indic_runs(aligned([KRSNA, "is", "Rājā", "Rājeśvara"]),
                           minimum=3, gap=1)
        self.assertEqual(found, [])

    def test_and_is_not_bridged(self):
        found = indic_runs(aligned(["rajo-guṇa", "tamo-guṇa", "and", "sattva-guṇa"]),
                           minimum=3, gap=1)
        self.assertEqual(found, [])

    def test_a_sanskrit_word_without_diacritics_is_still_bridged(self):
        # The whole reason gap=1 exists: SB 1.2.10 must not split on `ceha`.
        tokens = ["jīvasya", "tattva-jijñāsā", "nārtho",
                  "yaś", CEHA, "karmabhiḥ"]
        found = indic_runs(aligned(tokens), minimum=3, gap=1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["words"], 6)

    def test_an_english_lead_in_is_dropped_leaving_the_verse_alone(self):
        # `Srimad-Bhagavatam says, jivasya ... karmabhih` should yield the verse without the
        # English, which is a better query than the mixture.
        tokens = ["Śrīmad-Bhāgavatam", "says,", "jīvasya",
                  "tattva-jijñāsā", "nārtho", "yaś", CEHA,
                  "karmabhiḥ"]
        found = indic_runs(aligned(tokens), minimum=3, gap=1)
        self.assertEqual(len(found), 1)
        self.assertNotIn("says", found[0]["text"])
        self.assertIn("jīvasya", found[0]["text"])

    def test_punctuation_does_not_hide_an_english_word(self):
        found = indic_runs(aligned([KRSNA, '"But', "Gītā", "vāṇī"]),
                           minimum=3, gap=1)
        self.assertEqual(found, [])

    def test_case_does_not_hide_an_english_word(self):
        found = indic_runs(aligned([KRSNA, "In", "Rājā", "Rājeśvara"]),
                           minimum=3, gap=1)
        self.assertEqual(found, [])


class TermListTests(unittest.TestCase):
    """Almost every word ending in a comma is a list, not a verse line."""

    def test_a_comma_after_every_word_is_a_list(self):
        self.assertTrue(looks_like_a_list(
            "sādhu, bhakta, Vaiṣṇava, ācārya."))

    def test_a_verse_line_is_not_a_list(self):
        self.assertFalse(looks_like_a_list(
            "jīvasya tattvajijñāsā nārtho yaśceha karmabhiḥ"))

    def test_one_comma_in_a_verse_line_is_fine(self):
        # Printed verse does carry commas; it just does not carry one after every word.
        self.assertFalse(looks_like_a_list(
            "gharma-vṛṣội sahe, ānera karaye rakṣaṇa"))

    def test_a_term_list_is_not_returned_as_a_run(self):
        tokens = ["sādhu,", "bhakta,", "Vaiṣṇava,", "ācārya."]
        self.assertEqual(indic_runs(aligned(tokens), minimum=3, gap=1), [])

    def test_a_verse_run_survives_the_list_check(self):
        tokens = ["pratiṣthāśā", "āsi',", "hṛdoya", "dūṣibe,", "hoibo", "niraya-gāmī,"]
        found = indic_runs(aligned(tokens), minimum=3, gap=1)
        self.assertEqual(len(found), 1)
