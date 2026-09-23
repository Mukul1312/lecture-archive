"""Reading a KKSongs page.

The pages are Word exports from the 2000s, which matters more than it sounds: the source
wraps long lines with real newlines *inside* the text, so the line structure lives in the
tags and not in the whitespace. Getting that backwards cuts every lyric line in half, which
halves the signal the verse matcher has to work with.
"""

import unittest

from scripts.kksongs_mirror import FORBIDDEN, Song, parse_song

# The shape of a real page, reduced: Word markup, a source newline mid-line, a header split
# across two source lines, and a TRANSLATION section that must not be taken.
PAGE = """<html><body>
<p class=MsoNormal><b><span>Song
Name: Ab Ki Teka Hamari</span></b></p>

<p class=MsoNormal><span>Author:
Sura Dasa</span></p>

<p class=MsoNormal><span>Language:
Braja Bhasa</span></p>

<p class=MsoNormal><b><span>LYRICS:</span></b></p>

<p class=MsoNormal><span>(refrain)</span></p>

<p class=MsoNormal><span>ab
k&#299; t&#803;eka ham&#257;r&#299;</span></p>

<p class=MsoNormal><span>l&#257;ja
r&#257;kho giridh&#257;r&#299;</span></p>

<p class=MsoNormal><b><span>TRANSLATION</span></b></p>

<p class=MsoNormal><span>Please protect Sura Dasa, Oh protector of devotees.</span></p>
</body></html>"""


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.song = parse_song(PAGE, "http://kksongs.org/songs/a/abkitekahamari.html")

    def test_a_source_newline_does_not_split_a_lyric_line(self):
        # "ab\nkī ṭeka hamārī" is one line of the song, not two.
        self.assertIn("ab kī ṭeka hamārī", self.song.lyrics)

    def test_a_paragraph_break_does_split_lines(self):
        self.assertIn("lāja rākho giridhārī", self.song.lyrics)

    def test_the_header_fields_are_read(self):
        self.assertEqual(self.song.name, "Ab Ki Teka Hamari")
        self.assertEqual(self.song.author, "Sura Dasa")
        self.assertEqual(self.song.language, "Braja Bhasa")

    def test_the_translation_is_not_taken(self):
        # Somebody's translation is their work, and the archive does not need it.
        self.assertFalse(any("Please protect" in line for line in self.song.lyrics))

    def test_entities_become_the_letters_they_stand_for(self):
        self.assertIn("kī ṭeka hamārī", " ".join(self.song.lyrics))

    def test_a_field_set_to_none_is_left_empty(self):
        self.assertEqual(parse_song("<p>Book Name: None</p><p>LYRICS:</p><p>x y z</p>").book, "")

    def test_a_page_with_no_lyrics_marker_yields_none(self):
        self.assertEqual(parse_song("<p>Song Name: Silent</p>").lyrics, [])

    def test_the_song_carries_the_address_it_came_from(self):
        self.assertTrue(self.song.url.endswith("abkitekahamari.html"))


class PurportTests(unittest.TestCase):
    def test_the_purport_path_is_named_so_it_can_be_refused(self):
        # BBT and Prabhupada material, which is not KKSongs' to give away. The fetcher
        # refuses this path rather than relying on it never being linked.
        self.assertEqual(FORBIDDEN, "/authors/purports/")

    def test_a_song_starts_with_no_lyrics_rather_than_none(self):
        self.assertEqual(Song(url="x").lyrics, [])


if __name__ == "__main__":
    unittest.main()
