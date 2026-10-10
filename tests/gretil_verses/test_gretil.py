"""Reading GRETIL's TEI into printed verses, and the one repair it needs.

The sourcing research instructed: *"within a verse, drop any pada group identical to the one
before it. Write the regression test on SB 3.9.10 specifically."* That verse is one of the
Melbourne reference's own citations, and in the XML its first half-verse is printed twice. If
the repair regresses, every retrieval of a long-metre verse is matched against text containing
a line nobody recites twice - and worse, the archive would be told that is what the scripture
says.
"""

import unittest
from pathlib import Path

from scripts.gretil_verses import GRETIL, load, verses_from_tei

# The real encoding of SB 3.9.10, first half-verse duplicated exactly as GRETIL prints it.
SB_3_9_10 = """
<l>ahny &#257;p&#7771;t&#257;rta-kara&#7751;&#257; ni&#347;i ni&#7717;&#347;ay&#257;n&#257; $ n&#257;n&#257;-manoratha-dhiy&#257; k&#7779;a&#7751;a-bhagna-nidr&#257;&#7717; &amp;</l>
<l>ahny &#257;p&#7771;t&#257;rta-kara&#7751;&#257; ni&#347;i ni&#7717;&#347;ay&#257;n&#257; $ n&#257;n&#257;-manoratha-dhiy&#257; k&#7779;a&#7751;a-bhagna-nidr&#257;&#7717; &amp;</l>
<l>daiv&#257;hat&#257;rtha-racan&#257; &#7771;&#7779;ayo 'pi deva % yu&#7779;mat-prasa&#7749;ga-vimukh&#257; iha sa&#7747;saranti // BhP_03.09.010* //</l>
"""

# BhP 1.1.1 is starred but NOT duplicated, so the repair must leave it alone.
SB_1_1_1 = """
<l>janmadyasya yato 'nvayaditaratascarthesvabhijnah svarat $ tene brahma hrda ya adikavaye &amp;</l>
<l>tejovarimrdam yatha vinimayo yatra trisargo 'mrsa % dhamna svena sada nirastakuhakam // BhP_01.01.001* //</l>
"""

GITA = """
<p>BhG 3</p>
<lg>
<l>kama esa krodha esa rajo-guna-samudbhavah |</l>
<l>mahasano maha-papma viddhy enam iha vairinam ||BhG_3.37||</l>
</lg>
"""


class RepairTests(unittest.TestCase):
    def test_sb_3_9_10_keeps_its_first_half_verse_once(self):
        verse = verses_from_tei(SB_3_9_10)[0]
        self.assertEqual(verse.address, "SB 3.9.10")
        self.assertEqual(verse.text.count("bhagna-nidrāḥ"), 1)

    def test_sb_3_9_10_still_has_all_three_of_its_parts(self):
        # The repair must remove the copy, not the content.
        verse = verses_from_tei(SB_3_9_10)[0]
        for fragment in ("ahny", "nānā-manoratha-dhiyā", "saṃsaranti"):
            self.assertIn(fragment, verse.text)

    def test_a_starred_verse_without_duplication_is_untouched(self):
        verse = verses_from_tei(SB_1_1_1)[0]
        self.assertEqual(verse.address, "SB 1.1.1")
        self.assertIn("janmadyasya", verse.text)
        self.assertIn("tejovarimrdam", verse.text)

    def test_only_an_adjacent_copy_is_dropped(self):
        # A verse may legitimately repeat a line further along; this is a fix for a known
        # adjacent-duplication artefact, not licence to deduplicate a poem.
        xml = ("<l>hare krsna hare krsna $</l><l>something else %</l>"
               "<l>hare krsna hare krsna // BhP_01.01.009 //</l>")
        verse = verses_from_tei(xml)[0]
        self.assertEqual(verse.text.count("hare krsna hare krsna"), 2)


class ParsingTests(unittest.TestCase):
    def test_the_gita_pipe_convention_is_read_too(self):
        verse = verses_from_tei(GITA)[0]
        self.assertEqual(verse.address, "BG 3.37")
        self.assertIn("rajo-guna-samudbhavah", verse.text)
        self.assertFalse(verse.long_metre)

    def test_commentary_prose_is_not_mistaken_for_verse(self):
        # The Gita file is a commentary with prose paragraphs between the verses.
        self.assertEqual(len(verses_from_tei(GITA)), 1)

    def test_pada_markers_are_removed(self):
        verse = verses_from_tei(GITA)[0]
        for marker in ("|", "$", "%", "&", "/"):
            self.assertNotIn(marker, verse.text)

    def test_the_address_is_not_left_inside_the_text(self):
        self.assertNotIn("BhG", verses_from_tei(GITA)[0].text)

    def test_leading_zeros_are_normalised_away(self):
        self.assertEqual(verses_from_tei(SB_3_9_10)[0].address, "SB 3.9.10")

    def test_the_star_marks_a_long_metre_verse(self):
        self.assertTrue(verses_from_tei(SB_3_9_10)[0].long_metre)

    def test_lines_before_an_address_all_belong_to_that_verse(self):
        verse = verses_from_tei(GITA)[0]
        self.assertIn("kama esa", verse.text)
        self.assertIn("vairinam", verse.text)


@unittest.skipUnless((GRETIL / "sa_bhAgavatapurANa.xml").exists(),
                     "GRETIL not downloaded")
class RealCorpusTests(unittest.TestCase):
    """Against the actual files, because the fixtures above are my reading of them."""

    @classmethod
    def setUpClass(cls):
        cls.verses = {v.address: v for v in load()}

    def test_the_bhagavatam_citations_of_the_melbourne_reference_are_present(self):
        # The sourcing research named these five as present at their exact addresses.
        for address in ("SB 11.2.37", "SB 3.9.10", "SB 3.25.42", "SB 2.1.3", "SB 6.17.28"):
            self.assertIn(address, self.verses, address)

    def test_sb_3_9_10_is_repaired_in_the_real_file(self):
        self.assertEqual(self.verses["SB 3.9.10"].text.count("bhagna-nidrāḥ"), 1)

    def test_the_verse_the_archive_quotes_most_is_there(self):
        # SB 1.2.10 appeared six times across five lectures as unmatched fragments.
        self.assertIn("SB 1.2.10", self.verses)
        self.assertIn("jijñāsā", self.verses["SB 1.2.10"].text)

    def test_the_gita_stops_at_chapter_seventeen(self):
        # Documented: the cleanly-licensed file covers 1-17, and chapter 18 - which holds
        # BG 18.66, the archive's most-cited Gita verse - needs a separate source.
        self.assertIn("BG 17.1", self.verses)
        self.assertNotIn("BG 18.66", self.verses)


class WindowTests(unittest.TestCase):
    """A remembered fragment must be able to match something its own size.

    A GRETIL verse runs twelve to twenty words; the archive quotes four to thirteen, because a
    teacher cites a half-verse and carries on talking. Offering only whole verses identifies
    the quotation and then refuses to score it.
    """

    def test_the_padas_are_offered_as_well_as_the_whole_verse(self):
        verse = verses_from_tei(GITA)[0]
        windows = verse.windows()
        self.assertIn(verse.text, windows)
        self.assertTrue(any("vairinam" in w and "kama esa" not in w for w in windows))

    def test_a_window_is_never_a_duplicate_of_the_whole_verse(self):
        verse = verses_from_tei(GITA)[0]
        windows = verse.windows()
        self.assertEqual(windows.count(verse.text), 1)

    def test_a_single_line_verse_offers_just_itself(self):
        xml = "<l>hare krsna hare rama ||BhG_1.1||</l>"
        self.assertEqual(verses_from_tei(xml)[0].windows(), ["hare krsna hare rama"])
