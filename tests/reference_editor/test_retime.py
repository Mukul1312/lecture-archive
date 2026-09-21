from __future__ import annotations

import unittest

from scripts.reference_editor import review as review_model
from scripts.reference_editor.retime import HeardWord, fold, retime, write_srt


SRT = (
    "1\n00:00:01,000 --> 00:00:02,000\n<b>śrī-mārkaṇḍeya uvāca</b>\n\n"
    "2\n00:00:02,000 --> 00:00:04,000\n<b>O Lord Hari, I take shelter</b>\n\n"
    "3\n00:00:04,000 --> 00:00:05,000\n<b>hmm</b>\n\n"
    "4\n00:00:05,000 --> 00:00:08,000\n<b>of the soles of Your lotus feet</b>\n"
)


def say(text: str, start: float, step: float = 0.5) -> list[HeardWord]:
    return [HeardWord(token, start + i * step, start + i * step + 0.4) for i, token in enumerate(fold(text))]


class FoldTests(unittest.TestCase):

    def test_diacritics_and_punctuation_fold_to_plain_tokens(self) -> None:
        self.assertEqual(fold("śrī-mārkaṇḍeya uvāca"), ["sri", "markandeya", "uvaca"])
        self.assertEqual(fold("Your lotus-feet,"), ["your", "lotus", "feet"])


class RetimeTests(unittest.TestCase):

    def setUp(self) -> None:
        self.cues = review_model.parse_srt(SRT)
        # Heard 40 s later than the subtitles claim, with 10 s of speech the subtitles skipped.
        self.heard = (say("sri markandeya uvaca", 41.0)
                      + say("o lord hari i take shelter", 43.0)
                      + say("repeat the translation o lord hari i take shelter of the soles", 47.0, step=1.0)
                      + say("of the soles of your lotus feet", 60.0))

    def test_cues_take_their_time_from_where_their_words_were_heard(self) -> None:
        timings, report = retime(self.cues, self.heard)
        self.assertEqual(timings[0][0], 41_000)
        self.assertEqual(timings[1][0], 43_000)
        self.assertEqual(timings[3][0], 60_000, "cue 4 must follow its own words, not the repeated reading")
        self.assertEqual(report["cues_anchored"], 3)
        self.assertEqual(report["unmatched_cues"], [3])

    def test_an_unmatched_cue_sits_between_its_neighbours_and_order_is_kept(self) -> None:
        timings, _ = retime(self.cues, self.heard)
        starts = [start for start, _ in timings]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(starts[1] <= starts[2] <= starts[3])
        self.assertTrue(all(start <= end for start, end in timings))

    def test_speech_the_subtitles_skipped_is_reported(self) -> None:
        _, report = retime(self.cues, self.heard)
        self.assertEqual(len(report["spoken_but_not_subtitled"]), 1)
        start, end = report["spoken_but_not_subtitled"][0]
        self.assertTrue(46.0 <= start <= 48.0 and end >= 55.0, report["spoken_but_not_subtitled"])

    def test_sanskrit_glued_together_by_the_recogniser_still_matches(self) -> None:
        cues = review_model.parse_srt("1\n00:00:10,000 --> 00:00:12,000\n<b>prapanno ’smy aṅghri-mūlaṁ te</b>\n")
        heard = [HeardWord("prapannasmyangri", 12.0, 13.0), HeardWord("mulamte", 13.0, 14.0)]
        timings, report = retime(cues, heard)
        self.assertEqual(report["cues_anchored"], 1)
        self.assertEqual(timings[0][0], 12_000)

    def test_a_repeated_passage_goes_to_the_reading_nearest_the_expected_time(self) -> None:
        cues = review_model.parse_srt("1\n00:01:40,000 --> 00:01:44,000\n<b>O Lord Hari, I take shelter</b>\n")
        heard = say("o lord hari i take shelter", 95.0) + say("o lord hari i take shelter", 125.0)
        timings, _ = retime(cues, heard)
        self.assertEqual(timings[0][0], 95_000)

    def test_cues_stay_in_time_order_even_when_a_later_cue_matches_earlier_audio(self) -> None:
        cues = review_model.parse_srt(
            "1\n00:00:10,000 --> 00:00:12,000\n<b>the holy name is krishna</b>\n\n"
            "2\n00:00:12,000 --> 00:00:14,000\n<b>become fearless</b>\n")
        heard = say("become fearless", 5.0) + say("the holy name is krishna", 11.0) + say("become fearless", 14.0)
        timings, _ = retime(cues, heard)
        self.assertEqual([start for start, _ in timings], [11_000, 14_000])

    def test_rewritten_file_keeps_numbers_and_text_exactly(self) -> None:
        timings, _ = retime(self.cues, self.heard)
        rewritten = review_model.parse_srt(write_srt(self.cues, timings))
        self.assertEqual([(c.number, c.raw) for c in rewritten], [(c.number, c.raw) for c in self.cues])
        self.assertEqual([c.start_ms for c in rewritten], [start for start, _ in timings])


class CarryOverTests(unittest.TestCase):

    def test_work_moves_to_the_retimed_file_by_cue_number_and_words(self) -> None:
        old = review_model.new_review(SRT.encode("utf-8"), source_name="old.srt", audio="a.mp3")
        old["cues"][1].update(text="O Lord Hari, I take shelter,", status="fixed", note="comma heard")
        old["cues"][3]["status"] = "ok"
        old.update(offset_ms=-3000, session_notes="first minute is prayers", last_position_s=700.0)
        timings, _ = retime(review_model.parse_srt(SRT), say("sri markandeya uvaca o lord hari i take shelter", 41.0))
        retimed = write_srt(review_model.parse_srt(SRT), timings).encode("utf-8")
        baseline = review_model.new_review(retimed, source_name="new.srt", audio="a.mp3")

        carried, skipped = review_model.carry_over(old, baseline)

        self.assertEqual(skipped, [])
        self.assertEqual(carried["cues"][1]["text"], "O Lord Hari, I take shelter,")
        self.assertEqual(carried["cues"][1]["status"], "fixed")
        self.assertEqual(carried["cues"][1]["note"], "comma heard")
        self.assertEqual(carried["cues"][3]["status"], "ok")
        self.assertEqual(carried["cues"][0]["start_ms"], 41_000, "timings come from the re-timed file")
        self.assertEqual(carried["offset_ms"], 0, "re-timing replaces the listening offset")
        self.assertEqual((carried["session_notes"], carried["last_position_s"]), ("first minute is prayers", 700.0))

    def test_a_cue_whose_words_changed_is_not_carried_and_is_reported(self) -> None:
        old = review_model.new_review(SRT.encode("utf-8"), source_name="old.srt", audio="a.mp3")
        old["cues"][0].update(text="edited", status="fixed")
        changed = SRT.replace("śrī-mārkaṇḍeya uvāca", "śrī-mārkaṇḍeya uvāca ca")
        baseline = review_model.new_review(changed.encode("utf-8"), source_name="new.srt", audio="a.mp3")
        carried, skipped = review_model.carry_over(old, baseline)
        self.assertEqual(skipped, [1])
        self.assertEqual(carried["cues"][0]["status"], "unchecked")


if __name__ == "__main__":
    unittest.main()
