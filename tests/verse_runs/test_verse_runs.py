"""Finding recited verse in the archive, where the printed text can be the reference.

The archive cannot be used to choose a Sanskrit system because its transcripts carry Indic
words almost entirely as names inside English sentences - only 6.0% of its Indic tokens sit in
runs of five or more, against Melbourne's 24.6%. But what connected Indic there is should be
quotation, and a quotation has fixed printed text. Where a run can be matched to a printed
verse, ground truth is exact and free: no listening, no transcription.

So the two things worth testing are the extraction of those runs and the windowing of the
corpus they are matched against.
"""

import unittest

from scripts.verse_runs import indic_runs, song_windows


def words(*pairs):
    return [{"word": w, "start": float(i), "end": float(i) + 0.8}
            for i, (w, _) in enumerate(pairs)]


class IndicRunTests(unittest.TestCase):
    def test_a_run_of_three_is_found_with_its_times(self):
        aligned = [{"word": "he", "start": 0.0, "end": 0.5},
                   {"word": "said", "start": 0.6, "end": 1.0},
                   {"word": "k\u1e5b\u1e63\u1e47a", "start": 1.1, "end": 1.6},
                   {"word": "n\u0101ma", "start": 1.7, "end": 2.2},
                   {"word": "cint\u0101ma\u1e47i", "start": 2.3, "end": 3.0},
                   {"word": "today", "start": 3.1, "end": 3.5}]
        found = indic_runs(aligned, minimum=3)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["text"].split(), ["k\u1e5b\u1e63\u1e47a", "n\u0101ma",
                                                    "cint\u0101ma\u1e47i"])
        self.assertAlmostEqual(found[0]["start"], 1.1)
        self.assertAlmostEqual(found[0]["end"], 3.0)

    def test_a_shorter_run_is_not_returned(self):
        aligned = [{"word": "\u015ar\u012bla", "start": 0.0, "end": 0.5},
                   {"word": "Prabhup\u0101da", "start": 0.6, "end": 1.2},
                   {"word": "said", "start": 1.3, "end": 1.6}]
        self.assertEqual(indic_runs(aligned, minimum=3), [])

    def test_a_run_ending_at_the_last_word_is_still_closed(self):
        # An off-by-one here would silently lose every verse a lecture ends on.
        aligned = [{"word": "and", "start": 0.0, "end": 0.4},
                   {"word": "k\u1e5b\u1e63\u1e47a", "start": 0.5, "end": 1.0},
                   {"word": "n\u0101ma", "start": 1.1, "end": 1.5},
                   {"word": "cint\u0101ma\u1e47i", "start": 1.6, "end": 2.2}]
        found = indic_runs(aligned, minimum=3)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["end"], 2.2)

    def test_two_runs_separated_by_english_stay_separate(self):
        indic = ["k\u1e5b\u1e63\u1e47a", "n\u0101ma", "cint\u0101ma\u1e47i"]
        aligned = ([{"word": w, "start": float(i), "end": float(i) + 0.5}
                    for i, w in enumerate(indic)]
                   + [{"word": "then", "start": 9.0, "end": 9.4}]
                   + [{"word": w, "start": 10.0 + i, "end": 10.5 + i}
                      for i, w in enumerate(indic)])
        self.assertEqual(len(indic_runs(aligned, minimum=3)), 2)

    def test_a_window_may_be_restricted_to_the_scoreable_spans(self):
        aligned = [{"word": "k\u1e5b\u1e63\u1e47a", "start": 1.0, "end": 1.5},
                   {"word": "n\u0101ma", "start": 1.6, "end": 2.0},
                   {"word": "cint\u0101ma\u1e47i", "start": 2.1, "end": 2.6},
                   {"word": "k\u1e5b\u1e63\u1e47a", "start": 500.0, "end": 500.5},
                   {"word": "n\u0101ma", "start": 500.6, "end": 501.0},
                   {"word": "cint\u0101ma\u1e47i", "start": 501.1, "end": 501.6}]
        found = indic_runs(aligned, minimum=3, spans=[{"start": 0.0, "end": 100.0}])
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["start"], 1.0)


class SongWindowTests(unittest.TestCase):
    def test_lines_become_windows_of_one_and_two(self):
        songs = [{"name": "A", "language": "Bengali",
                  "lyrics": ["jaya radha madhava", "kunja bihari", "gopi jana vallabha"]}]
        verses, passages = song_windows(songs, sizes=(1, 2))
        self.assertIn("jaya radha madhava", verses)
        self.assertIn("jaya radha madhava kunja bihari", verses)
        self.assertEqual(set(passages), {"A"})

    def test_a_window_never_crosses_two_songs(self):
        # Crossing would invent a verse that nobody ever wrote, and the margin would then be
        # defended against a line that does not exist.
        songs = [{"name": "A", "language": "Bengali", "lyrics": ["alpha beta", "gamma delta"]},
                 {"name": "B", "language": "Bengali", "lyrics": ["epsilon zeta", "eta theta"]}]
        verses, _ = song_windows(songs, sizes=(2,))
        self.assertNotIn("gamma delta epsilon zeta", verses)

    def test_structural_markers_are_not_indexed_as_verse(self):
        songs = [{"name": "A", "language": "Bengali",
                  "lyrics": ["(1)", "jaya radha madhava", "(refrain)"]}]
        verses, _ = song_windows(songs, sizes=(1,))
        self.assertEqual(verses, ["jaya radha madhava"])

    def test_songs_in_a_european_language_are_left_out(self):
        songs = [{"name": "A", "language": "Spanish", "lyrics": ["a orillas del kalindi"]},
                 {"name": "B", "language": "Sanskrit", "lyrics": ["govindam adi purusam"]}]
        verses, passages = song_windows(songs, sizes=(1,))
        self.assertEqual(passages, ["B"])
