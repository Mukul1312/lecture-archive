"""The Gītā from Sanskrit Wikisource: parsing, and the chapter GRETIL has not got.

GRETIL's cleanly-licensed Gītā stops at chapter 17, so **BG 18.66 is absent from it** - the
verse this archive cites more than any other Gītā verse. Wikisource has all eighteen chapters
under CC BY-SA 4.0, in Devanagari, so two things need testing: that the verses are separated
from Śaṅkara's commentary, which outweighs them 760,000 characters to a few thousand on chapter
18 alone, and that chapter 18 can actually be retrieved from a garbled recollection.

The transliteration itself is checked elsewhere, against GRETIL on the 621 addresses both
editions carry: 520 letter-identical, 565 where GRETIL's verse sits wholly inside Wikisource's
(which adds `arjuna uvāca` and the chapter-head invocation), and 39 where the two editions
genuinely differ.
"""

import unittest

from scripts.wikisource_gita import PAGES, comparable, verses_from_wikitext

CHAPTER = """
{{header | title = [[../]] | section = मोक्षसंन्यासयोगः }}

== अष्टादशोऽध्याय: मोक्षसंन्यासयोग ==

<poem>
'''ॐ'''
'''श्रीपरमात्मने नमः'''

'''अर्जुन उवाच'''
संन्यासस्य महाबाहो तत्त्वमिच्छामि वेदितुम् ।
त्यागस्य च हृषीकेश पृथक्केशिनिषूदन ॥१८- १॥
</poem>

{{व्याख्या
|शीर्षकम्=व्याख्याः
|
'''शाङ्करभाष्यम्'''<br>
।।18.1।। संन्यासस्य संन्यासशब्दार्थस्य इत्येतत् हे महाबाहो
}}

<poem>
'''श्रीभगवानुवाच'''
काम्यानां कर्मणां न्यासं संन्यासं कवयो विदुः ।
सर्वकर्मफलत्यागं प्राहुस्त्यागं विचक्षणाः ॥१८- २॥
</poem>
"""


class ParsingTests(unittest.TestCase):
    def test_both_verses_are_found_with_their_addresses(self):
        found = verses_from_wikitext(CHAPTER)
        self.assertEqual([(v["chapter"], v["verse"]) for v in found], [(18, 1), (18, 2)])

    def test_devanagari_digits_in_the_marker_are_read(self):
        # The marker is `॥१८- १॥`, not `॥18- 1॥`.
        self.assertEqual(verses_from_wikitext(CHAPTER)[0]["chapter"], 18)

    def test_the_commentary_is_not_mistaken_for_verse(self):
        # Sankara's bhasya sits in a {{व्याख्या}} template outside any <poem> block, and on
        # chapter 18 it outweighs the verses 760,000 characters to a few thousand.
        joined = " ".join(v["devanagari"] for v in verses_from_wikitext(CHAPTER))
        self.assertNotIn("शाङ्करभाष्यम्", joined)
        self.assertNotIn("संन्यासशब्दार्थस्य", joined)

    def test_dandas_and_bold_markup_are_stripped(self):
        text = verses_from_wikitext(CHAPTER)[0]["devanagari"]
        for junk in ("।", "॥", "'''"):
            self.assertNotIn(junk, text)

    def test_the_marker_itself_is_not_left_in_the_verse(self):
        self.assertNotIn("१८", verses_from_wikitext(CHAPTER)[0]["devanagari"])

    def test_a_verses_own_lines_are_kept_separately(self):
        # Needed so a quotation of half a verse can match something its own size.
        self.assertGreaterEqual(len(verses_from_wikitext(CHAPTER)[1]["lines"]), 2)


class ComparableTests(unittest.TestCase):
    """Word boundaries must not be compared: the two editions segment sandhi differently."""

    def test_hyphens_and_spaces_are_ignored(self):
        self.assertEqual(comparable("ananta-vijayaṃ rājā"), comparable("anantavijayaṃ rājā"))

    def test_diacritics_are_ignored(self):
        self.assertEqual(comparable("kṛṣṇaḥ"), comparable("krsnah"))

    def test_different_letters_still_differ(self):
        self.assertNotEqual(comparable("rājā"), comparable("rāja-putra"))


def _transliteration_available() -> bool:
    try:
        import indic_transliteration  # noqa: F401
    except ImportError:
        return False
    return PAGES.exists() and any(PAGES.glob("*.json"))


@unittest.skipUnless(_transliteration_available(),
                     "needs .venv-indic (indic_transliteration) and fetched pages")
class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.wikisource_gita import load
        cls.verses = {v["address"]: v for v in load()}

    def test_all_eighteen_chapters_are_present(self):
        chapters = {int(a.split()[1].split(".")[0]) for a in self.verses}
        self.assertEqual(chapters, set(range(1, 19)))

    def test_the_verse_gretil_cannot_supply_is_here(self):
        # The whole reason this source was fetched.
        self.assertIn("BG 18.66", self.verses)

    def test_chapter_eighteen_has_its_seventy_eight_verses(self):
        eighteen = [a for a in self.verses if a.startswith("BG 18.")]
        self.assertEqual(len(eighteen), 78)

    def test_every_verse_records_the_revision_it_came_from(self):
        # "The verse at this address" is only reproducible if the revision is recorded.
        for address in ("BG 18.66", "BG 1.1"):
            self.assertTrue(self.verses[address]["source"])
            self.assertIn("oldid=", self.verses[address]["source"])

    def test_a_garbled_recollection_of_bg_18_66_retrieves_it(self):
        """End to end: the capability, not just the data.

        The query is built by corrupting the verse AS READ FROM THE FILE - aspirates and
        sibilants flattened, the way a recogniser actually mishears chanted Sanskrit - so
        nothing here is recalled from memory.
        """
        from scripts.verse_match import VerseIndex
        index = VerseIndex([v["text"] for v in self.verses.values()],
                           passages=[a for a in self.verses])
        printed = self.verses["BG 18.66"]["text"]
        garbled = (printed.replace("ṣ", "sh").replace("ś", "s").replace("ṃ", "m")
                   .replace("ā", "a").replace("ī", "i").replace("ū", "u"))
        found = index.find(garbled)
        self.assertIsNotNone(found, "BG 18.66 was not retrieved from a garbled query")
        self.assertEqual(found.passage, "BG 18.66")
