from __future__ import annotations

import copy
from pathlib import Path
import unittest

from scripts.reference_editor import review as review_model


SRT = (
    "1\r\n00:00:01,000 --> 00:00:02,500\r\n<b>śrī-mārkaṇḍeya uvāca</b>\r\n\r\n"
    "2\r\n00:00:02,500 --> 00:00:05,000\r\n<b>Take shelter of this </b>\r\n<b>Holy Name &amp; be fearless</b>\r\n\r\n"
    "3\r\n00:00:05,000 --> 00:00:06,000\r\n<inaudible> said the typist\r\n"
)
MELBOURNE = Path(__file__).resolve().parents[2] / "data" / "reference" / "MELBOURNE_vs_90-85_synced.srt"


def fresh() -> dict:
    return review_model.new_review(SRT.encode("utf-8"), source_name="ref.srt", audio="clip.mp3")


class ParseTests(unittest.TestCase):

    def test_cues_keep_number_timing_and_words_without_formatting_tags(self) -> None:
        review = fresh()
        self.assertEqual([cue["n"] for cue in review["cues"]], [1, 2, 3])
        self.assertEqual((review["cues"][1]["start_ms"], review["cues"][1]["end_ms"]), (2500, 5000))
        self.assertEqual(review["cues"][0]["original"], "śrī-mārkaṇḍeya uvāca")
        self.assertEqual(review["cues"][1]["original"], "Take shelter of this\nHoly Name & be fearless")
        self.assertTrue(all(cue["status"] == "unchecked" and cue["text"] == cue["original"] for cue in review["cues"]))

    def test_transcriber_markers_are_words_not_formatting(self) -> None:
        self.assertEqual(fresh()["cues"][2]["original"], "<inaudible> said the typist")

    def test_source_digest_is_lowercase_sha256(self) -> None:
        digest = fresh()["source_srt_sha256"]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_malformed_subtitles_are_refused(self) -> None:
        cases = {
            "gap in numbering": "1\n00:00:01,000 --> 00:00:02,000\nA\n\n3\n00:00:02,000 --> 00:00:03,000\nB\n",
            "bad time": "1\n00:00:01 --> 00:00:02,000\nA\n",
            "ends before it starts": "1\n00:00:05,000 --> 00:00:02,000\nA\n",
            "starts before the previous cue": "1\n00:00:05,000 --> 00:00:06,000\nA\n\n2\n00:00:01,000 --> 00:00:02,000\nB\n",
        }
        for label, text in cases.items():
            with self.subTest(label), self.assertRaises(review_model.ReviewError):
                review_model.parse_srt(text)

    @unittest.skipUnless(MELBOURNE.exists(), "local reference file not present (it is gitignored)")
    def test_the_melbourne_reference_parses_into_512_cues(self) -> None:
        review = review_model.new_review(MELBOURNE.read_bytes(), source_name=MELBOURNE.name, audio="x")
        self.assertEqual(len(review["cues"]), 512)
        self.assertEqual(review["cues"][0]["original"], "śrī-mārkaṇḍeya uvāca")


class ValidateTests(unittest.TestCase):

    def setUp(self) -> None:
        self.baseline = fresh()

    def test_edits_to_words_status_and_notes_are_accepted(self) -> None:
        submitted = copy.deepcopy(self.baseline)
        submitted["cues"][1].update(text="Take shelter of the Holy Name", status="ok", note="checked twice")
        submitted["cues"][2]["status"] = "unsure"
        submitted.update(offset_ms=3500, last_position_s=812.4, session_notes="first minute is an announcement")
        clean = review_model.validate_review(submitted, baseline=self.baseline)
        self.assertEqual(clean["cues"][1]["status"], "fixed", "a checked cue with changed words is a correction")
        self.assertEqual(clean["cues"][1]["note"], "checked twice")
        self.assertEqual(clean["cues"][2]["status"], "unsure")
        self.assertEqual((clean["offset_ms"], clean["last_position_s"]), (3500, 812.4))

    def test_a_checked_cue_with_original_words_is_ok_not_fixed(self) -> None:
        submitted = copy.deepcopy(self.baseline)
        submitted["cues"][0]["status"] = "fixed"
        self.assertEqual(review_model.validate_review(submitted, baseline=self.baseline)["cues"][0]["status"], "ok")

    def test_timings_and_original_words_cannot_be_changed(self) -> None:
        for key, value in (("start_ms", 999), ("end_ms", 1), ("n", 7), ("original", "rewritten")):
            submitted = copy.deepcopy(self.baseline)
            submitted["cues"][0][key] = value
            with self.subTest(key), self.assertRaises(review_model.ReviewError):
                review_model.validate_review(submitted, baseline=self.baseline)

    def test_reviews_that_do_not_match_the_subtitles_are_refused(self) -> None:
        mutations = {
            "other subtitle file": lambda r: r.update(source_srt_sha256="0" * 64),
            "missing cue": lambda r: r["cues"].pop(),
            "unknown status": lambda r: r["cues"][0].update(status="done"),
            "text not a string": lambda r: r["cues"][0].update(text=None),
            "offset out of range": lambda r: r.update(offset_ms=120_000),
            "negative position": lambda r: r.update(last_position_s=-1),
            "wrong schema": lambda r: r.update(schema="other/1"),
        }
        for label, mutate in mutations.items():
            submitted = copy.deepcopy(self.baseline)
            mutate(submitted)
            with self.subTest(label), self.assertRaises(review_model.ReviewError):
                review_model.validate_review(submitted, baseline=self.baseline)


class ExportTests(unittest.TestCase):

    def test_exported_srt_has_corrected_words_original_timings_and_round_trips(self) -> None:
        review = fresh()
        review["cues"][1]["text"] = "Take shelter of the Holy Name\nand become fearless"
        review["cues"][2]["text"] = "   "
        exported = review_model.export_srt(review)
        self.assertIn("\r\n", exported)
        cues = review_model.parse_srt(exported)
        self.assertEqual([(c.number, c.start_ms, c.end_ms) for c in cues], [(1, 1000, 2500), (2, 2500, 5000), (3, 5000, 6000)])
        self.assertEqual(review_model.plain_text(cues[1].raw), "Take shelter of the Holy Name\nand become fearless")
        self.assertEqual(review_model.plain_text(cues[2].raw), review_model.NO_SPEECH)

    def test_change_log_lists_corrected_unsure_and_annotated_cues_only(self) -> None:
        review = fresh()
        review["cues"][1].update(text="Take shelter of the Holy Name", status="fixed")
        review["cues"][2].update(status="unsure", note="two voices overlap")
        log = review_model.change_log(review)
        self.assertIn("Checked 1 of 3 cues: 0 unchanged, 1 corrected. 1 unsure, 1 not yet checked.", log)
        self.assertIn("### Cue 2", log)
        self.assertIn("- Corrected: Take shelter of the Holy Name", log)
        self.assertIn("- Note: two voices overlap", log)
        self.assertNotIn("### Cue 1 ", log)


if __name__ == "__main__":
    unittest.main()
