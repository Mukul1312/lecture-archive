"""Taking the verse and nothing but the verse from the Vedabase corpus.

The steward holds full permission from BBT, which is what makes this source available at all.
That permission is not a reason to take more than the task needs: each file holds the verse,
then word-for-word synonyms, then the translation, then Prabhupāda's purport, and only the
verse is wanted. The verse is 400-year-old text by Kṛṣṇadāsa Kavirāja and is what a recogniser
is graded against; the purport is a living teacher's commentary and is not.

So the first tests here are scope tests. If they ever fail, the index has stopped holding
scripture and started holding somebody's commentary on it.
"""

import unittest

from scripts.bbt_verses import CORPUS, verse_from_file

ADI_17_21 = """---json
{
    "name":"Cc. Ādi 17.21",
    "h1":"Cc. Ādi 17.21",
    "label":"Text 21",
    "title":"Śrī Caitanya-caritāmṛta, Ādi-līlā 17.21",
    "description":"\\" 'In this Age of Kali there is no other means'"
}
---

====== Cc. Ādi 17.21 ======

===== Text =====

> harer nāma harer nāma
> harer nāmaiva kevalam
> kalau nāsty eva nāsty eva
> nāsty eva gatir anyathā

===== Synonyms =====

[[synonyms:h:hareḥ]] [[synonyms:n:nāma]]---the holy name of the Lord; [[synonyms:e:eva]]---certainly

===== Translation =====

"'In this Age of Kali there is no other means for self-realization than chanting the holy name.'"

===== Purport =====

This verse is quoted from the Brhan-naradiya Purana, and Srila Jiva Gosvami explains at length
that the chanting of the holy name is the only means in this age.
"""

NO_VERSE = """---json
{"name":"Cc. Ādi 1 Summary"}
---

====== Chapter Summary ======

===== Purport =====

This chapter describes the glories of the Lord.
"""


class ScopeTests(unittest.TestCase):
    def test_only_the_verse_text_is_taken(self):
        address, lines = verse_from_file(ADI_17_21)
        self.assertEqual(address, "Cc. Ādi 17.21")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], "harer nāma harer nāma")

    def test_the_purport_is_not_taken(self):
        _, lines = verse_from_file(ADI_17_21)
        joined = " ".join(lines)
        self.assertNotIn("Jiva Gosvami", joined)
        self.assertNotIn("Brhan-naradiya", joined)

    def test_the_translation_is_not_taken(self):
        _, lines = verse_from_file(ADI_17_21)
        self.assertNotIn("self-realization", " ".join(lines))

    def test_the_synonyms_are_not_taken(self):
        _, lines = verse_from_file(ADI_17_21)
        joined = " ".join(lines)
        self.assertNotIn("holy name of the Lord", joined)
        self.assertNotIn("synonyms:", joined)


class ParsingTests(unittest.TestCase):
    def test_the_address_comes_from_the_files_own_header(self):
        self.assertEqual(verse_from_file(ADI_17_21)[0], "Cc. Ādi 17.21")

    def test_a_file_with_no_verse_returns_nothing(self):
        # Chapter summaries carry no Text section, and inventing a verse for them would put
        # prose into the index as scripture.
        self.assertIsNone(verse_from_file(NO_VERSE))

    def test_the_quote_markers_are_removed(self):
        _, lines = verse_from_file(ADI_17_21)
        self.assertFalse(any(line.startswith(">") for line in lines))

    def test_the_lines_are_kept_separately(self):
        # So a quotation of one line can match a window its own size.
        self.assertEqual(len(verse_from_file(ADI_17_21)[1]), 4)


@unittest.skipUnless(CORPUS.exists() and any(CORPUS.rglob("*.txt")), "corpus not cloned")
class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.bbt_verses import load
        cls.verses = {v.address: v for v in load()}

    def test_all_three_lilas_are_present(self):
        # Reuses setUpClass's load: parsing 11,429 files twice cost the suite 110 seconds.
        self.assertEqual({v.lila for v in self.verses.values()}, {"adi", "madhya", "antya"})

    def test_the_verse_the_archive_quotes_is_there(self):
        self.assertIn("Cc. Ādi 17.21", self.verses)

    def test_no_purport_text_leaked_into_any_verse(self):
        # The scope guarantee, over the whole corpus rather than one fixture. English
        # sentences in a Bengali verse index mean the section boundaries were misread.
        giveaways = ("Supreme Personality of Godhead", "spiritual master", "therefore")
        offenders = [v.address for v in self.verses.values()
                     if any(g in v.text for g in giveaways)]
        self.assertEqual(offenders[:5], [], f"{len(offenders)} verses contain prose")
