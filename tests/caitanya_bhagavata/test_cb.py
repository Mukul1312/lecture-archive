"""Parsing Caitanya-bhagavata from a scanned full text, where both landmarks can be wrong.

Each verse is announced by a printed `Text 95` header and closed by a `//CB, Antya 1.095//`
marker. Both are OCR output. The real file's marker for Text 95 reads `1.0905` - a stray digit -
so trusting the marker alone would file that verse at 1.905, which does not exist, and trusting
the header alone would lose the chapter. Chapter comes from the marker, verse number from the
printed header, and a disagreement is counted rather than hidden.

And only the verse is taken: TRANSLATION and COMMENTARY close it, by the same rule the rest of
the corpus follows.
"""

import unittest

from scripts.caitanya_bhagavata import CORPUS, verses_from_archive_text

# The real shape of the file, including the stray-digit marker on Text 95.
REAL = """
Text 1

avatirnau sa-karunyau paricchinnau sad-isvarau
sri-krsna-caitanya-nityanandau dvau bhratarau bhaje//CB, Antya 1.001//

TRANSLATION

I worship the two brothers, Sri Krsna Caitanya and Sri Nityananda, who
have descended in this world as the supreme controllers.

COMMENTARY

See Adi-khanda, Chapter One, verse 3.

Text 95

hena bujhi kari' prabhu vakresvara-vyaja

dhanya karilena sarva radhera samaja//CB, Antya 1.0905//

TRANSLATION

Thus I understand that the Lord glorified all of Radha's associates.

Text 301

hena-mate mahanande sri-gaurasundara
ailena kata dine kataka-nagara//CB, Antya 2.301//

TRANSLATION

In this way Sri Gaurasundara happily arrived at Kataka.
"""


class AddressTests(unittest.TestCase):
    def test_all_three_verses_are_found(self):
        self.assertEqual(len(verses_from_archive_text(REAL)), 3)

    def test_the_printed_label_wins_over_a_stray_digit_in_the_marker(self):
        # The marker says 1.0905; the printed header says Text 95. 1.905 does not exist.
        got = {v.address for v in verses_from_archive_text(REAL)}
        self.assertIn("CB Antya 1.95", got)
        self.assertNotIn("CB Antya 1.905", got)

    def test_the_chapter_still_comes_from_the_marker(self):
        # The printed header carries no chapter at all, so the marker is needed for it.
        got = {v.address for v in verses_from_archive_text(REAL)}
        self.assertIn("CB Antya 2.301", got)

    def test_a_disagreement_is_recorded_not_silently_resolved(self):
        verses = {v.address: v for v in verses_from_archive_text(REAL)}
        self.assertTrue(verses["CB Antya 1.95"].label_disagreed)
        self.assertFalse(verses["CB Antya 1.1"].label_disagreed)

    def test_the_khanda_is_normalised(self):
        self.assertTrue(all(v.khanda == "Antya" for v in verses_from_archive_text(REAL)))


class ScopeTests(unittest.TestCase):
    def test_the_translation_is_not_part_of_the_verse(self):
        verses = {v.address: v for v in verses_from_archive_text(REAL)}
        self.assertNotIn("supreme controllers", verses["CB Antya 1.1"].text)

    def test_the_commentary_is_not_part_of_the_verse(self):
        verses = {v.address: v for v in verses_from_archive_text(REAL)}
        self.assertNotIn("Chapter One", verses["CB Antya 1.1"].text)

    def test_one_verse_does_not_swallow_the_previous_ones_commentary(self):
        # The hazard of anchoring on the next marker: reaching back past the previous verse
        # would pull its translation and commentary into this one.
        verses = {v.address: v for v in verses_from_archive_text(REAL)}
        self.assertNotIn("I worship", verses["CB Antya 1.95"].text)
        self.assertNotIn("See Adi-khanda", verses["CB Antya 1.95"].text)

    def test_the_verse_keeps_all_of_its_own_lines(self):
        verses = {v.address: v for v in verses_from_archive_text(REAL)}
        self.assertIn("hena bujhi", verses["CB Antya 1.95"].text)
        self.assertIn("radhera samaja", verses["CB Antya 1.95"].text)

    def test_the_marker_is_not_left_in_the_text(self):
        for verse in verses_from_archive_text(REAL):
            self.assertNotIn("//CB", verse.text)

    def test_a_scanned_page_number_is_not_a_word_of_the_verse(self):
        text = REAL.replace("hena bujhi kari' prabhu vakresvara-vyaja",
                            "412\n\nhena bujhi kari' prabhu vakresvara-vyaja")
        verses = {v.address: v for v in verses_from_archive_text(text)}
        self.assertNotIn("412", verses["CB Antya 1.95"].text)


@unittest.skipUnless(CORPUS.exists() and any(CORPUS.glob("*_djvu.txt")),
                     "Caitanya-bhagavata text not downloaded")
class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.caitanya_bhagavata import load
        cls.verses = {v.address: v for v in load()}

    def test_the_antya_khanda_is_substantially_present(self):
        antya = [a for a in self.verses if a.startswith("CB Antya ")]
        self.assertGreater(len(antya), 3000)

    def test_the_opening_verse_is_there_and_is_the_verse(self):
        self.assertIn("CB Antya 1.1", self.verses)
        self.assertIn("bhratarau bhaje", self.verses["CB Antya 1.1"].text)

    def test_no_english_prose_leaked_into_the_verses(self):
        # The scope guarantee over the whole khanda rather than over a fixture.
        giveaways = ("TRANSLATION", "COMMENTARY", "respectful obeisances", "In this way")
        offenders = [a for a, v in self.verses.items()
                     if any(g in v.text for g in giveaways)]
        self.assertEqual(offenders[:5], [], f"{len(offenders)} verses contain prose")
