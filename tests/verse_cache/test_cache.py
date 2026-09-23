"""The cache that becomes the corpus, and the allowlist that keeps it shippable.

Verses are resolved by search once and remembered forever, keyed by the same phonetic
skeleton the matcher uses, so a different garbling of the same verse finds the same entry.
The allowlist is the load-bearing part: without it a search can return vedabase, and
Bhaktivedanta Book Trust text would enter the archive's corpus silently.
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verse_cache import SOURCES, VerseCache, source_allowed

VERSE = "prapanno 'smy aṅghri-mūlaṁ te prapannābhaya-daṁ hare"
HEARD = "upaja prapanna asmiyangri malam ti prapanna bhaya dum hari"
OTHER_GARBLING = "upaya prapanna asamiyam ghrmalanti prapanna bhayadam hari"


class AllowlistTests(unittest.TestCase):
    def test_a_licensed_source_is_allowed(self):
        self.assertTrue(source_allowed("https://gretil.sub.uni-goettingen.de/gretil/corpustei/x.xml"))

    def test_vedabase_is_refused_because_it_is_bbt(self):
        self.assertFalse(source_allowed("https://vedabase.io/en/library/sb/3/9/10/"))

    def test_an_unknown_site_is_refused_by_default(self):
        # Default deny: a source nobody has checked the licence of does not get in.
        self.assertFalse(source_allowed("https://some-random-blog.example/verse"))

    def test_the_subdomain_cannot_be_used_to_sneak_past(self):
        self.assertFalse(source_allowed("https://vedabase.io.evil.example/x"))

    def test_every_listed_source_carries_a_reason(self):
        for host, entry in SOURCES.items():
            with self.subTest(host=host):
                self.assertTrue(entry.get("why"), f"{host} has no stated reason")
                self.assertIn(entry.get("allow"), (True, False))


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

    def test_a_forbidden_source_is_refused_and_nothing_is_stored(self):
        with self.assertRaises(ValueError):
            self.cache.remember(HEARD, VERSE, "https://vedabase.io/en/library/sb/3/9/10/")
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
