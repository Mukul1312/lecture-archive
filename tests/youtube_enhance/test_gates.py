import unittest

import numpy as np

from scripts.youtube_enhance.gates import (
    CandidateRejected,
    approve_candidate,
    gate_report,
    identity_verdict,
    longest_new_zero_run,
    score_candidate_windows,
)


class GateTests(unittest.TestCase):
    def test_identity_fails_more_than_point_zero_three_below_anchor(self):
        self.assertTrue(identity_verdict(0.90, 0.871))
        self.assertFalse(identity_verdict(0.90, 0.869))

    def test_new_zero_run_ignores_a_matching_original_dropout(self):
        original = np.ones(30, dtype=np.float32)
        original[3:8] = 0
        candidate = original.copy()
        candidate[15:25] = 0
        self.assertEqual(longest_new_zero_run(original, candidate), 10)

    def test_failed_blind_code_cannot_be_approved(self):
        report = _report()
        report["shortlist"] = ["A"]
        report["report_sha256"] = _report_hash(report)
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "C", "original", "Mukul", "fingerprint", private_blind_map=report["blind_map"])

    def test_gate_report_only_shortlists_candidates_passing_every_veto(self):
        metrics = {
            "original": _metrics(),
            "adaptive-22": _metrics(identity_mean=0.86),
            "adaptive-24": _metrics(non_finite_samples=1),
        }
        report = gate_report(
            {"A": "original", "B": "adaptive-22", "C": "adaptive-24"}, metrics, 48000,
            processing_fingerprint="fingerprint-a",
        )
        self.assertEqual(report["shortlist"], ["A"])
        self.assertEqual(report["decisions"]["B"]["reasons"], ["identity"])
        self.assertEqual(report["decisions"]["C"]["reasons"], ["non-finite"])
        self.assertNotIn("adaptive-22", report["metrics"])

    def test_original_pause_approval_binds_current_report_evidence(self):
        report = _report()
        approval = approve_candidate(report, "B", "original", "Mukul", "fingerprint", private_blind_map=report["blind_map"])
        self.assertEqual(approval["evidence_sha256"], report["report_sha256"])
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "B", "original", "Mukul", "other-fingerprint", private_blind_map=report["blind_map"])
        report["decisions"]["B"]["pass"] = False
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "B", "original", "Mukul", "fingerprint", private_blind_map=report["blind_map"])

    def test_strong_pause_approval_requires_hashed_matching_blind_evidence(self):
        report = _report()
        report["strong_pause_passed"] = True
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "B", "approved-strong", "Mukul", "fingerprint", private_blind_map=report["blind_map"])
        report["strong_pause_evidence"] = {
            "blind_code": "B",
            "passed": True,
            "processing_fingerprint": "fingerprint",
            "report_sha256": report["report_sha256"],
        }
        report["strong_pause_evidence"]["evidence_sha256"] = "tampered"
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "B", "approved-strong", "Mukul", "fingerprint", private_blind_map=report["blind_map"])
        report["strong_pause_evidence"]["evidence_sha256"] = _pause_hash(report["strong_pause_evidence"])
        approval = approve_candidate(report, "B", "approved-strong", "Mukul", "fingerprint", private_blind_map=report["blind_map"])
        self.assertEqual(approval["candidate_id"], "adaptive-22")
        self.assertEqual(approval["fingerprint"], "fingerprint")

    def test_new_zero_run_measures_the_entire_candidate_run_across_original_holes(self):
        original = np.ones(40, dtype=np.float32)
        original[15:17] = 0
        candidate = original.copy()
        candidate[10:30] = 0
        self.assertEqual(longest_new_zero_run(original, candidate), 20)

    def test_invalid_adaptive_input_is_vetoed_before_any_heavy_scorer(self):
        original = np.ones((10, 2), dtype=np.float32) * 0.1
        invalid = original.copy()
        invalid[0, 0] = np.nan
        raw = {
            "one": {
                "original": original,
                "adaptive-22": invalid,
                "adaptive-24": original.copy(),
            },
            "two": {
                candidate_id: original.copy()
                for candidate_id in ("original", "adaptive-22", "adaptive-24")
            },
        }
        calls = []
        metrics = score_candidate_windows(
            raw,
            ["one", "two"],
            16000,
            speech_intervals={"one": (0, 10), "two": (10, 20)},
            scoring_seams={"encoder_factory": lambda: calls.append("encoder")},
        )
        self.assertEqual(calls, [])
        self.assertEqual(metrics["adaptive-22"]["non_finite_samples"], 1)
        self.assertEqual(metrics["adaptive-22"]["status"], "invalid-preflight")

    def test_invalid_adaptive_does_not_prevent_a_valid_sibling_from_scoring(self):
        speech = np.full((15 * 16000, 2), 0.1, dtype=np.float32)
        invalid = speech.copy()
        invalid[0, 0] = np.nan
        raw = {
            "one": {"original": speech.copy(), "adaptive-22": invalid, "adaptive-24": speech.copy()},
            "two": {"original": speech.copy(), "adaptive-22": invalid.copy(), "adaptive-24": speech.copy()},
        }
        calls = []
        seams = {
            "encoder_factory": lambda: calls.append("encoder") or object(),
            "embed_chunks": lambda _encoder, chunks, _rate: np.tile(np.array([[1.0, 0.0]]), (len(chunks), 1)),
            "voice_quality": lambda *_args: {"cpps": 1.0, "hnr": 1.0, "hammarberg": 1.0, "alpha_std": 1.0},
            "mfcc_distance": lambda *_args: 0.0,
            "pumping_index": lambda *_args: 0.0,
        }
        metrics = score_candidate_windows(raw, ["one", "two"], 16000, speech_intervals={"one": (0, 240000), "two": (240000, 480000)}, scoring_seams=seams)
        self.assertEqual(calls, ["encoder"])
        self.assertEqual(metrics["adaptive-22"]["status"], "invalid-preflight")
        self.assertEqual(metrics["adaptive-24"]["status"], "scored")
        self.assertIsInstance(metrics["adaptive-24"]["identity_mean"], float)

    def test_approval_rejects_private_map_swap(self):
        report = _report()
        swapped = dict(report["blind_map"])
        swapped["A"], swapped["B"] = swapped["B"], swapped["A"]
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "B", "original", "Mukul", "fingerprint", private_blind_map=swapped)

    def test_approval_rejects_mutated_report_map_even_when_private_commitment_is_correct(self):
        report = _report()
        private_map = dict(report["blind_map"])
        report["blind_map"]["B"] = "original"
        with self.assertRaises(CandidateRejected):
            approve_candidate(report, "B", "original", "Mukul", "fingerprint", private_blind_map=private_map)

    def test_long_new_zero_run_is_vetoed_before_encoder_creation(self):
        original = np.ones((900, 2), dtype=np.float32) * 0.1
        zeroed = original.copy()
        zeroed[:, :] = 0.0
        calls = []
        metrics = score_candidate_windows(
            {
                "one": {
                    "original": original,
                    "adaptive-22": zeroed,
                    "adaptive-24": original.copy(),
                },
                "two": {
                    candidate_id: original.copy()
                    for candidate_id in ("original", "adaptive-22", "adaptive-24")
                },
            },
            ["one", "two"], 16000,
            speech_intervals={"one": (0, 900), "two": (900, 1800)},
            scoring_seams={"encoder_factory": lambda: calls.append("encoder")},
        )
        self.assertEqual(calls, [])
        self.assertEqual(metrics["adaptive-22"]["longest_new_zero_run_samples"], 900)

    def test_valid_anchor_zero_run_veto_skips_only_failed_adaptive_heavy_work(self):
        original = np.full((15 * 16000, 2), 0.1, dtype=np.float32)
        failed = np.full((15 * 16000, 2), 0.2, dtype=np.float32)
        failed[:900] = 0.0
        valid = np.full((15 * 16000, 2), 0.3, dtype=np.float32)
        raw = {
            "one": {"original": original.copy(), "adaptive-22": failed, "adaptive-24": valid.copy()},
            "two": {"original": original.copy(), "adaptive-22": failed.copy(), "adaptive-24": valid.copy()},
        }
        calls = {"encoder": 0, "embed": [], "voice": [], "mfcc": [], "pump": []}
        def tag(values):
            amplitude = float(values[1000, 0])
            if np.isclose(amplitude, 0.1):
                return "original"
            if np.isclose(amplitude, 0.2):
                return "adaptive-22"
            if np.isclose(amplitude, 0.3):
                return "adaptive-24"
            raise AssertionError(f"unexpected candidate amplitude: {amplitude}")
        def embed(_encoder, chunks, _rate):
            tags = [tag(chunk[:, None]) for chunk in chunks]
            self.assertEqual(tags, [tags[0]] * len(tags))
            calls["embed"].append((tags[0], len(chunks)))
            return np.tile(np.array([[1.0, 0.0]]), (len(chunks), 1))
        def voice(values, _rate, _directory, name):
            calls["voice"].append((name, tag(values)))
            return {"cpps": 1.0, "hnr": 1.0, "hammarberg": 1.0, "alpha_std": 1.0}
        def mfcc(reference, candidate):
            calls["mfcc"].append((tag(reference[:, None]), tag(candidate[:, None])))
            return 0.0
        def pump(values):
            calls["pump"].append(tag(values))
            return 0.0
        seams = {
            "encoder_factory": lambda: calls.__setitem__("encoder", calls["encoder"] + 1) or object(),
            "embed_chunks": embed,
            "voice_quality": voice,
            "mfcc_distance": mfcc,
            "pumping_index": pump,
        }
        metrics = score_candidate_windows(raw, ["one", "two"], 16000, speech_intervals={"one": (0, 240000), "two": (240000, 480000)}, scoring_seams=seams)
        self.assertEqual(metrics["adaptive-22"]["status"], "invalid-preflight")
        self.assertEqual(metrics["adaptive-24"]["status"], "scored")
        self.assertEqual(calls["encoder"], 1)
        self.assertEqual(calls["embed"], [("original", 2), ("adaptive-24", 2)])
        self.assertEqual(calls["voice"], [("original", "original"), ("original", "original"), ("adaptive-24", "adaptive-24")])
        self.assertEqual(calls["mfcc"], [("original", "original"), ("original", "adaptive-24")])
        self.assertEqual(calls["pump"], ["original", "original", "adaptive-24", "original"])
        observed_tags = (
            [value[0] for value in calls["embed"]]
            + [name for name, _tag in calls["voice"]]
            + [audio_tag for _name, audio_tag in calls["voice"]]
            + [candidate_tag for _reference_tag, candidate_tag in calls["mfcc"]]
            + calls["pump"]
        )
        self.assertNotIn("adaptive-22", observed_tags)
        report = gate_report({"A": "original", "B": "adaptive-22", "C": "adaptive-24"}, metrics, 16000, processing_fingerprint="fingerprint")
        self.assertIn("new-zero-run", report["decisions"]["B"]["reasons"])

    def test_anchor_rejects_duplicate_or_overlapping_interval_provenance_before_heavy_work(self):
        original = np.ones((10, 2), dtype=np.float32) * 0.1
        raw = {"one": {"original": original, "adaptive-22": original, "adaptive-24": original}}
        with self.assertRaises(ValueError):
            score_candidate_windows(raw, ["one", "one"], 16000, speech_intervals={"one": (0, 10)})
        raw["two"] = {"original": original, "adaptive-22": original, "adaptive-24": original}
        with self.assertRaises(ValueError):
            score_candidate_windows(
                raw, ["one", "two"], 16000,
                speech_intervals={"one": (0, 10), "two": (5, 15)},
            )

    def test_one_thirty_second_source_interval_cannot_supply_both_identity_anchors(self):
        speech = np.full((30 * 16000, 2), 0.1, dtype=np.float32)
        raw = {
            "speech": {
                "original": speech,
                "adaptive-22": speech,
                "adaptive-24": speech,
            }
        }
        with self.assertRaisesRegex(
            ValueError, "identity anchor requires at least two unique source intervals"
        ):
            score_candidate_windows(
                raw,
                ["speech"],
                16000,
                speech_intervals={"speech": (0, 30 * 16000)},
                scoring_seams={
                    "encoder_factory": lambda: (_ for _ in ()).throw(
                        AssertionError("one source interval reached the encoder")
                    )
                },
            )

    def test_two_unique_intervals_still_require_two_complete_fifteen_second_chunks(self):
        first = np.full((15 * 16000, 2), 0.1, dtype=np.float32)
        second = np.full((14 * 16000, 2), 0.1, dtype=np.float32)
        raw = {
            "one": {candidate_id: first for candidate_id in ("original", "adaptive-22", "adaptive-24")},
            "two": {candidate_id: second for candidate_id in ("original", "adaptive-22", "adaptive-24")},
        }
        with self.assertRaisesRegex(
            ValueError, "identity anchor requires at least two 15-second speech chunks"
        ):
            score_candidate_windows(
                raw,
                ["one", "two"],
                16000,
                speech_intervals={
                    "one": (0, 15 * 16000),
                    "two": (15 * 16000, 29 * 16000),
                },
                scoring_seams={
                    "encoder_factory": lambda: (_ for _ in ()).throw(
                        AssertionError("incomplete chunks reached the encoder")
                    )
                },
            )

    def test_transition_discontinuity_is_measured_at_explicit_excerpt_boundaries(self):
        speech = np.full((15 * 16000, 2), 0.1, dtype=np.float32)
        transition = np.array([[0.1, 0.1], [0.1, 0.1], [0.9, 0.9], [0.1, 0.1]], dtype=np.float32)
        raw = {
            "speech-one": {candidate: speech.copy() for candidate in ("original", "adaptive-22", "adaptive-24")},
            "speech-two": {candidate: speech.copy() for candidate in ("original", "adaptive-22", "adaptive-24")},
            "transition": {candidate: transition.copy() for candidate in ("original", "adaptive-22", "adaptive-24")},
        }
        raw["transition"]["adaptive-22"][2] = 0.5
        seams = {
            "encoder_factory": lambda: object(),
            "embed_chunks": lambda _encoder, chunks, _rate: np.tile(np.array([[1.0, 0.0]]), (len(chunks), 1)),
            "voice_quality": lambda *_args: {"cpps": 1.0, "hnr": 1.0, "hammarberg": 1.0, "alpha_std": 1.0},
            "mfcc_distance": lambda *_args: 0.0,
            "pumping_index": lambda *_args: 0.0,
        }
        metrics = score_candidate_windows(
            raw,
            ["speech-one", "speech-two"],
            16000,
            speech_intervals={"speech-one": (0, 240000), "speech-two": (240000, 480000)},
            transition_windows={"transition": (2,)},
            scoring_seams=seams,
        )
        evidence = metrics["adaptive-22"]["transition_evidence"]["transition"]
        self.assertEqual(evidence["boundaries"], [2])
        self.assertAlmostEqual(evidence["peak_discontinuity"], 0.4, places=5)
        self.assertAlmostEqual(metrics["adaptive-22"]["transition_peak_discontinuity"], 0.4, places=5)


def _metrics(**overrides):
    value = {
        "natural_anchor_mean": 0.90,
        "identity_mean": 0.90,
        "longest_new_zero_run_samples": 0,
        "sample_count_equal": True,
        "non_finite_samples": 0,
        "peak": 0.99,
    }
    value.update(overrides)
    return value


def _report():
    metrics = {candidate: _metrics() for candidate in ("original", "adaptive-22", "adaptive-24")}
    return gate_report(
        {"A": "original", "B": "adaptive-22", "C": "adaptive-24"},
        metrics,
        48000,
        processing_fingerprint="fingerprint",
    )


def _pause_hash(evidence):
    from scripts.youtube_enhance.gates import canonical_evidence_hash

    return canonical_evidence_hash({key: value for key, value in evidence.items() if key != "evidence_sha256"})


def _report_hash(report):
    from scripts.youtube_enhance.gates import gate_evidence_hash

    return gate_evidence_hash(report)


if __name__ == "__main__":
    unittest.main()
