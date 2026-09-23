"""The cache that becomes the corpus, and the provenance it insists on.

Verses are resolved by search once and remembered forever. Lookup is fuzzy, through the
matcher's own index, because no two recognisers garble a verse the same way.

The licences are settled, so sources are recorded rather than gated. What is still enforced
is that a verse has an address at all: text with no source is text a model produced instead
of locating, and models reproduce scripture exactly 32.6% of the time in English.
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verse_cache import BLOCKED, SOURCES, VerseCache, source_allowed

VERSE = "prapanno 'smy aṅghri-mūlaṁ te prapannābhaya-daṁ hare"
HEARD = "upaja prapanna asmiyangri malam ti prapanna bhaya dum hari"
OTHER_GARBLING = "upaya prapanna asamiyam ghrmalanti prapanna bhayadam hari"


class SourceTests(unittest.TestCase):
    def test_a_known_source_is_accepted(self):
        self.assertTrue(source_allowed("https://gretil.sub.uni-goettingen.de/gretil/corpustei/x.xml"))

    def test_an_unlisted_source_is_accepted_too(self):
        # The licences are settled; this is a record, not a gate.
        self.assertTrue(source_allowed("https://www.wisdomlib.org/hinduism/book/x"))

    def test_a_source_the_steward_blocked_is_refused(self):
        BLOCKED.add("blocked.example")
        try:
            self.assertFalse(source_allowed("https://blocked.example/verse"))
        finally:
            BLOCKED.discard("blocked.example")

    def test_something_that_is_not_a_url_is_refused(self):
        self.assertFalse(source_allowed("I remember this verse"))

    def test_every_noted_source_says_what_is_known_of_it(self):
        for host, entry in SOURCES.items():
            with self.subTest(host=host):
                self.assertTrue(entry.get("why"), f"{host} has no note")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cache = VerseCache(Path(self.dir.name) / "verses.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_remembered_verse_comes_back(self):
        self.cache.remember(HEARD, VERSE, "https://gretil.sub.uni-goettingen.de/x.xml")
        self.assertEqual(self.cache.recall(HEARD).verse, VERSE)

    def test_a_different_garbling_of_the_same_verse_hits_the_same_entry(self):
        # This is what makes the cache worth having: he quotes the same canon for 3,766
        # lectures and no two recognitions of it are identical.
        self.cache.remember(HEARD, VERSE, "https://gretil.sub.uni-goettingen.de/x.xml")
        self.assertEqual(self.cache.recall(OTHER_GARBLING).verse, VERSE)

    def test_a_verse_never_seen_is_a_miss(self):
        self.assertIsNone(self.cache.recall("do you understand mr peter"))

    def test_a_blocked_source_is_refused_and_nothing_is_stored(self):
        BLOCKED.add("blocked.example")
        try:
            with self.assertRaises(ValueError):
                self.cache.remember(HEARD, VERSE, "https://blocked.example/x")
        finally:
            BLOCKED.discard("blocked.example")
        self.assertIsNone(self.cache.recall(HEARD))

    def test_a_verse_with_no_source_is_refused(self):
        # Text the model produced rather than found has no URL, and is exactly what must
        # never enter the corpus.
        with self.assertRaises(ValueError):
            self.cache.remember(HEARD, VERSE, "")

    def test_the_cache_survives_being_reopened(self):
        self.cache.remember(HEARD, VERSE, "https://gretil.sub.uni-goettingen.de/x.xml")
        again = VerseCache(self.cache.path)
        self.assertEqual(again.recall(OTHER_GARBLING).verse, VERSE)

    def test_the_source_is_kept_with_every_entry(self):
        self.cache.remember(HEARD, VERSE, "https://kksongs.org/songs/p/prapanno.html")
        entry = self.cache.recall(HEARD)
        self.assertEqual(entry.source, "https://kksongs.org/songs/p/prapanno.html")

    def test_the_file_on_disk_is_readable_by_a_person(self):
        self.cache.remember(HEARD, VERSE, "https://gretil.sub.uni-goettingen.de/x.xml")
        stored = json.loads(self.cache.path.read_text(encoding="utf-8"))
        self.assertIn("verses", stored)
        self.assertEqual(stored["verses"][0]["verse"], VERSE)


if __name__ == "__main__":
    unittest.main()
