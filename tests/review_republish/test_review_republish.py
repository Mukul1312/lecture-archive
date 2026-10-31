"""Republishing a published package as its next version, so that every agreed piece is asked.

Answers name a package by its bytes, so a published package never changes; a new question goes
into a new version. Answers carry over by stop id (agreed 29 October 2026), so the new version
must still ask every earlier question in exactly the same words, and may only add. It is built
from the published bytes, never by building the first version again: the code has moved on since,
and a rebuild could draw different stops under the same ids.
"""

import json
import unittest
from pathlib import Path

from scripts.review_contract import package_rules, republish_rules, schema_errors
from scripts.review_package import (TrustedSpan, Word, assemble, difference_stops,
                                    disagreement_draft, piece_draft, span_differences)
from scripts.review_republish import republish

EXAMPLE = Path("contracts/review/examples/valid/package-bg-3-37-brisbane.json")
SHA = "ab" * 32
NOW = "2026-11-01T06:00:00Z"


def words(text: str, start: float = 100.0, step: float = 0.4) -> list[Word]:
    return [Word(w, round(start + i * step, 3), round(start + i * step + 0.3, 3))
            for i, w in enumerate(text.split())]


def aligned(published: list[Word]) -> list[dict]:
    """The aligner's timed words, as `lecture_words` returns them, with their unrounded times."""
    return [{"word": w.text, "index": i, "start": w.start, "end": w.end}
            for i, w in enumerate(published) if w.start is not None]


def package_of(drafts: list[dict], published: list[Word], heard: list[Word], languages: list[str],
               spans: list[TrustedSpan]) -> dict:
    package = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    stops, transcript = assemble(package["lecture"]["id"], drafts,
                                 package["lecture"]["duration_seconds"], published, languages,
                                 spans, heard, outside=[])
    package.update(trustworthy_spans=[{"start": round(s.start, 3), "end": round(s.end, 3)}
                                      for s in spans],
                   untranscribed=[], transcript={"words": transcript}, stops=stops)
    return package


def first_version(with_disagreement: bool = True) -> tuple[dict, list[Word], list[Word], list[dict]]:
    """A small published v1 as the default mode builds it: a disagreement and one random sample."""
    published = words("we must hear the bona fide teacher who knows the truth and acts on it today")
    heard = words("we must hear a bona fide teacher who knows the truth and acts on it today")
    languages = ["english"] * 16
    spans = [TrustedSpan(published[0].start, published[-1].end, 0, 15)]
    [difference] = difference_stops(published, heard, languages)
    drafts = [piece_draft((10, 16, 10, 16), published, heard, languages, set(), set())]
    if with_disagreement:
        drafts.append(disagreement_draft(difference, published, heard))
    package = package_of(drafts, published, heard, languages, spans)
    return package, published, heard, aligned(published)


class RepublishTests(unittest.TestCase):
    def test_the_next_version_keeps_every_stop_and_asks_every_other_agreed_piece(self):
        previous, published, heard, timed = first_version()
        current, summary = republish(previous, SHA, published, heard, timed, revision="1" * 40,
                                     now=NOW)
        self.assertEqual(schema_errors("lecture-review-package", current), [])
        self.assertEqual(package_rules(current), [])
        self.assertEqual(republish_rules(previous, current), [])

        lecture = previous["lecture"]["id"]
        self.assertEqual(current["package"], {"id": f"{lecture}/v2", "version": 2,
                                              "published_at": NOW})
        for field in ("schema", "lecture", "audio", "alignment_check", "trustworthy_spans",
                      "untranscribed"):
            self.assertEqual(current[field], previous[field])
        # v1 numbered the disagreement #0001 and the sample #0002; the new pieces come after,
        # so the ids are no longer in timeline order, though the stops still are.
        self.assertEqual([s["id"].rpartition("#")[2] for s in current["stops"]],
                         ["0003", "0001", "0004", "0002"])
        self.assertEqual([[w["text"] for w in s["versions"][0]["words"]] for s in current["stops"]
                          if s["id"].endswith(("#0003", "#0004"))],
                         [["we", "must", "hear"], ["bona", "fide", "teacher", "who", "knows", "the"]])
        self.assertTrue(all(w["stop"] for w in current["transcript"]["words"]))
        # Neither new piece shows the disagreement's "the" or "a" as context.
        first, second = (s for s in current["stops"] if s["id"].endswith(("#0003", "#0004")))
        self.assertEqual([v["after"] for v in first["versions"]], [[], []])
        self.assertEqual([v["before"] for v in second["versions"]], [[], []])
        self.assertTrue(current["producer"]["notes"].startswith(
            f"Republishes v1 (SHA-256 {SHA}), keeping its 2 stops unchanged; adds 2 agreement "
            f"stops, one for every agreed piece where both texts are exactly the same."))
        self.assertEqual(summary["new"], 2)

    def test_inputs_that_are_not_the_words_the_first_version_was_built_from_are_refused(self):
        previous, published, heard, timed = first_version()
        published[5] = Word("fyde", published[5].start, published[5].end)
        with self.assertRaisesRegex(ValueError, "not the word"):
            republish(previous, SHA, published, heard, timed, revision="1" * 40, now=NOW)

    def test_a_first_version_the_comparison_would_not_draw_again_is_refused(self):
        # Without its disagreement, v1 is not what today's comparison draws from these words, so
        # its stops and the new pieces could not be trusted to fit together.
        previous, published, heard, timed = first_version(with_disagreement=False)
        with self.assertRaisesRegex(ValueError, "disagreements"):
            republish(previous, SHA, published, heard, timed, revision="1" * 40, now=NOW)

    def test_a_span_is_read_at_its_unrounded_edge_as_the_first_version_was(self):
        # Found on the evening darshan: a span starts at 1414.378210 s and the package stores
        # 1414.378. ElevenLabs's "So" sits at 1414.3780, outside the span as built, so v1 asks the
        # published "So" alone. Read at the rounded edge, the "So"s pair and that stop vanishes.
        published = [Word("So", 100.0, 100.06)] + words("you got his mercy", start=100.08)
        heard = [Word("So", 99.95, 100.05)] + words("you got his mercy", start=100.11)
        timed = aligned(published)
        timed[0]["start"] = 100.000210
        span = TrustedSpan(timed[0]["start"], published[-1].end, 0, 4)
        drafts = [disagreement_draft(s, published, heard)
                  for s in span_differences(span, published, heard, ["english"] * 5, [])]
        self.assertEqual([d["versions"][1]["words"] for d in drafts], [[]])   # "So" asked alone
        previous = package_of(drafts, published, heard, ["english"] * 5, [span])
        current, _ = republish(previous, SHA, published, heard, timed, revision="1" * 40, now=NOW)
        self.assertEqual(republish_rules(previous, current), [])


if __name__ == "__main__":
    unittest.main()
