"""A 200 response is not necessarily the page you asked for.

28 of 7,800 fetched pages came back at about 22 KB against a normal 57, carrying the correct
`<title>` (`Verse 2.1.70 Shri Chaitanya Bhagavata`) and the boilerplate words "English
translation" and "Commentary", but no verse. `curl` returns the same bytes, so nothing was lost
in transit: the tail is `/cdn-cgi/challenge-platform/scripts/jsd/main.js` — **Cloudflare's bot
challenge**, served after several thousand requests from one client.

The danger was not the challenge but the saving of it: once written to disk the file exists, so
resume never asks again, and the hole becomes permanent and invisible. So a page is checked for
the thing it was fetched for before it is saved.
"""

import unittest

from scripts.wisdomlib_cb import looks_complete, verse_from_page

WHOLE = """<html><head><title>Verse 1.1.118 Shri Chaitanya Bhagavata</title></head><body>
<p>Bengali text, Devanagari and Unicode transliteration of verse 1.1.118:</p>
<p>বাল্য-লীলা ঃ ১১৮ ঃ</p>
<p>बाल्य-लीला ॥ ११८ ॥</p>
<p>bālya-līlā-ādi kari yateka prakāśa || 118 ||</p>
<p>balya-lila-adi kari yateka prakasa (118)</p>
<p>English translation:</p>
<p>(118) The Adi-khanda begins with the Lord's childhood pastimes.</p>
</body></html>"""

# The real failure: Cloudflare's challenge page, with the correct title on it.
CHALLENGE = """<html><head><title>Verse 2.1.70 Shri Chaitanya Bhagavata</title></head><body>
<script>const d=(c)=>String.fromCharCode(...c); const c=[ [49,50,56,48,120,49,50,48,48],
[49,51,54,54,120,49,51,54,54], [56,48,48,120,54,48,48], [51,56,52,48,120,50,49,54,48]"""


class CompletenessTests(unittest.TestCase):
    def test_a_whole_page_is_accepted(self):
        self.assertTrue(looks_complete(WHOLE))

    def test_a_challenge_page_is_rejected_despite_a_correct_title(self):
        # The title is the trap: it looks like the page you asked for.
        self.assertIn("Verse 2.1.70", CHALLENGE)
        self.assertFalse(looks_complete(CHALLENGE))

    def test_an_empty_response_is_rejected(self):
        self.assertFalse(looks_complete(""))

    def test_the_check_tests_for_the_thing_being_fetched(self):
        # A page is fetched for its verse, so the verse block's absence is the right test:
        # anything looks_complete accepts must actually yield a verse.
        self.assertTrue(looks_complete(WHOLE))
        self.assertIsNotNone(verse_from_page(WHOLE))

    def test_a_rejected_page_would_have_yielded_nothing_anyway(self):
        self.assertIsNone(verse_from_page(CHALLENGE))
