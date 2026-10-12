"""The ground-truth set exists so scoring stops being an argument.

Every claim about the verse matcher in this project has so far been settled by reading
candidates and forming a view — which is exactly how the margin error happened: a distribution
was read as evidence about causes, and the actual refusals, once read, said something else.

`tests/fixtures/verse_truth.json` freezes those readings. A scoring change is an improvement
only if it resolves more `correct` runs to their recorded address **without** resolving any
`refuse` run to any address at all. Those two counts move in opposite directions under every
loosening of the gate, which is the whole reason to write them down before touching anything.

These tests do not measure the matcher — that needs the 192,911-window index and takes minutes.
They guard the fixture itself, so it cannot rot into something that silently tests nothing.
"""

import json
import pathlib
import unicodedata
import unittest

FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "tests/fixtures/verse_truth.json"


class FixtureIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.runs = cls.data["runs"]

    def test_the_provenance_says_who_judged_it_and_that_it_is_unverified(self):
        # It is my reading, not the steward's, and a later session must not mistake it for
        # ground truth handed down from outside.
        provenance = self.data["provenance"]
        self.assertIn("Claude", provenance)
        self.assertIn("NOT independently verified", provenance)

    def test_every_run_has_a_verdict(self):
        for run in self.runs:
            self.assertIn(run["verdict"], {"correct", "refuse", "unresolved"}, run["heard"][:40])

    def test_nothing_is_left_unjudged(self):
        # An unjudged run is a silent hole: it would be counted as neither a win nor a loss.
        self.assertEqual([r for r in self.runs if r["verdict"] == "unjudged"], [])

    def test_every_correct_run_carries_an_address_and_a_reason(self):
        for run in self.runs:
            if run["verdict"] == "correct":
                self.assertTrue(run.get("address"), run["heard"][:40])
                self.assertTrue(run.get("why"), run["heard"][:40])
                self.assertIn(run.get("confidence"), {"high", "medium", "low"})

    def test_a_refusal_carries_no_address(self):
        # Any address for these is a wrong answer, so storing one would corrupt the measurement.
        for run in self.runs:
            if run["verdict"] == "refuse":
                self.assertIsNone(run.get("address"), run["heard"][:40])

    def test_uncertain_judgements_are_marked_rather_than_averaged_away(self):
        # The point is that the doubt stays visible. At least one entry is not confident, and
        # the fixture must keep saying so.
        soft = [r for r in self.runs
                if r["verdict"] == "unresolved" or r.get("confidence") in {"low", "medium"}]
        self.assertTrue(soft, "the uncertainty has been quietly removed")

    def test_the_counts_match_the_rows(self):
        for verdict, count in self.data["counts"].items():
            self.assertEqual(count, sum(1 for r in self.runs if r["verdict"] == verdict),
                             verdict)

    def test_every_run_carries_a_normalised_key_beside_the_verbatim_text(self):
        """These transcripts mix precomposed and decomposed diacritics.

        `pratiṣthāśā` written by hand and `pratiṣthāśā` as the pipeline emits it print
        identically and compare unequal. `skeleton()` never notices because it runs NFKD first;
        a fixture comparing text does, and this one silently missed a run until both sides were
        normalised.

        So `heard` stays verbatim - it has to, or a lookup against the pipeline's own output
        fails - and `key` carries the normalisation that comparisons use. Storing only one of
        the two reintroduces the trap from whichever side is missing.
        """
        for run in self.runs:
            self.assertIn("key", run, run["heard"][:40])
            self.assertEqual(run["key"], unicodedata.normalize("NFC", run["heard"]),
                             run["heard"][:40])

    def test_the_keys_are_unique_so_a_lookup_cannot_be_ambiguous(self):
        keys = [r["key"] for r in self.runs]
        self.assertEqual(len(keys), len(set(keys)))

    def test_there_is_enough_of_each_class_to_measure_anything(self):
        counts = self.data["counts"]
        self.assertGreaterEqual(counts["correct"], 15)
        self.assertGreaterEqual(counts["refuse"], 3)
