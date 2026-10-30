"""The shared review format, as both projects must read it.

`contracts/review/` is the published format between this repository and the review app. The
app checks the same examples with Ajv and its own TypeScript rules, so these tests are the
Python half of one agreement: every golden example must give exactly the result
`examples/index.json` states. A failing example must break the rule it names and no other,
because an example that breaks two rules proves nothing about either.

The schema cannot compare one field with another, so the rules in the format's README (P1-P10,
A1-A9, C1-C3, R1) are code. Only seven of them have an invalid example, so each of the others is
broken here once, in memory, on a copy of the valid example.
"""

import copy
import hashlib
import json
import unittest

from scripts.review_contract import (CONTRACT, accepted_rules, answer_rules, package_rules,
                                     read_items, refuse_unknown_version, results_rules,
                                     schema_errors)

EXAMPLES = CONTRACT / "examples"
INDEX = json.loads((EXAMPLES / "index.json").read_text(encoding="utf-8"))


def sha(name: str) -> str:
    return hashlib.sha256((EXAMPLES / name).read_bytes()).hexdigest()


def items(name: str) -> list:
    return read_items(EXAMPLES / name)


def broken(example: dict, found: list) -> set[str]:
    """Which rules the example's records break, checked against the files it names."""
    kind = example["schema"].removesuffix(".schema.json")
    if kind == "lecture-review-package":
        return {b.rule for b in package_rules(found[0])}
    if kind == "review-answers":
        package = example["package"]
        return {b.rule for b in answer_rules(found, {sha(package): items(package)[0]})}
    if kind == "accepted-answers":
        return {b.rule for b in accepted_rules(found[0], items(example["package"])[0],
                                               sha(example["package"]), items(example["answers"]),
                                               sha(example["answers"]))}
    return {b.rule for b in results_rules(found[0], sha(example["package"]),
                                          items(example["answers"]), sha(example["answers"]),
                                          items(example["accepted"])[0], sha(example["accepted"]))}


class GoldenExampleTests(unittest.TestCase):
    def test_every_example_gives_the_result_its_index_states(self):
        self.assertTrue(INDEX["examples"])
        for example in INDEX["examples"]:
            with self.subTest(example["file"]):
                kind = example["schema"].removesuffix(".schema.json")
                found = items(example["file"])
                errors = [e for item in found for e in schema_errors(kind, item)]
                if example["expect"] == "fails-schema":
                    self.assertTrue(errors, "the schema accepted an example that must fail it")
                    continue
                self.assertEqual(errors, [])
                expected = set() if example["expect"] == "valid" else {example["rule"]}
                self.assertEqual(broken(example, found), expected)

    def test_every_example_file_is_listed_in_the_index(self):
        # An unlisted example is checked by nobody, on either side.
        listed = {example["file"] for example in INDEX["examples"]}
        on_disk = {p.relative_to(EXAMPLES).as_posix() for p in EXAMPLES.rglob("*.json*")} - {"index.json"}
        self.assertEqual(on_disk, listed)

    def test_the_example_answers_name_the_example_package_by_its_real_hash(self):
        # The hash is over bytes, so a CRLF checkout would break it without changing a word.
        package_sha = sha("valid/package-bg-3-37-brisbane.json")
        for record in items("valid/answers-bg-3-37-brisbane.jsonl"):
            self.assertEqual(record["package"]["sha256"], package_sha)


class VersionTests(unittest.TestCase):
    def test_a_newer_minor_version_is_refused_until_the_reader_is_updated(self):
        package = items("valid/package-bg-3-37-brisbane.json")[0]
        refuse_unknown_version("lecture-review-package", package)
        package["schema"] = "lecture-review-package/1.1"
        self.assertEqual(schema_errors("lecture-review-package", package), [])
        with self.assertRaises(ValueError):
            refuse_unknown_version("lecture-review-package", package)


def valid_package() -> dict:
    return copy.deepcopy(items("valid/package-bg-3-37-brisbane.json")[0])


def stop(package: dict, serial: str) -> dict:
    return next(s for s in package["stops"] if s["id"].endswith(serial))


class PackageRuleTests(unittest.TestCase):
    """Each rule broken once, so a rule that never fires cannot pass unnoticed."""

    def assertBreaks(self, package: dict, rule: str):
        self.assertEqual(schema_errors("lecture-review-package", package), [])
        self.assertEqual({b.rule for b in package_rules(package)}, {rule})

    def test_the_valid_example_breaks_nothing(self):
        self.assertEqual(package_rules(valid_package()), [])

    def test_p2_a_span_that_runs_backwards(self):
        package = valid_package()
        package["untranscribed"][1] = {"start": 2516.495, "end": 2506.442}
        self.assertBreaks(package, "P2")

    def test_p2_a_word_with_only_one_time(self):
        package = valid_package()
        stop(package, "#0012")["versions"][0]["words"][0]["end"] = None
        self.assertBreaks(package, "P2")

    def test_p2_an_untimed_word_that_did_not_come_from_the_published_text(self):
        # Only the aligner leaves a word unplaced; a recogniser's word always has its time.
        package = valid_package()
        word = stop(package, "#0012")["versions"][1]["words"][0]
        word["start"] = word["end"] = None
        self.assertBreaks(package, "P2")

    def test_p3_a_clip_that_does_not_cover_its_stop(self):
        package = valid_package()
        stop(package, "#0088")["context"]["end"] = 1217.0
        # Its last word now lies outside the clip as well, so P10 fires with it.
        self.assertEqual({b.rule for b in package_rules(package)}, {"P3", "P10"})

    def test_p5_a_stop_id_from_another_lecture(self):
        package = valid_package()
        old = stop(package, "#0088")["id"]
        stop(package, "#0088")["id"] = "another-lecture#0088"
        for word in package["transcript"]["words"]:
            if word["stop"] == old:
                word["stop"] = "another-lecture#0088"
        self.assertBreaks(package, "P5")

    def test_p5_a_transcript_word_naming_a_stop_that_does_not_exist(self):
        package = valid_package()
        package["transcript"]["words"][0]["stop"] = package["lecture"]["id"] + "#9999"
        self.assertBreaks(package, "P5")

    def test_p6_a_listening_copy_of_a_different_length(self):
        package = valid_package()
        package["audio"]["listening_copy"]["seconds"] = 3649.2
        self.assertBreaks(package, "P6")

    def test_p7_an_agreement_sample_whose_versions_differ(self):
        package = valid_package()
        stop(package, "#0175")["versions"][1]["words"][1]["text"] = "properly"
        self.assertBreaks(package, "P7")

    def test_p7_a_differing_position_beyond_the_words(self):
        package = valid_package()
        stop(package, "#0012")["versions"][0]["differs"] = [0, 1]
        self.assertBreaks(package, "P7")

    def test_p8_a_recited_position_beyond_the_printed_words(self):
        package = valid_package()
        stop(package, "#0089")["verse"]["recited"] = [0, 3]
        self.assertBreaks(package, "P8")

    def test_p9_text_not_in_nfc(self):
        package = valid_package()
        stop(package, "#0012")["versions"][0]["before"][0] = "Kṛṣṇa"
        self.assertBreaks(package, "P9")

    def test_p10_a_word_outside_its_clip(self):
        # The clip still covers the stop; one of the stop's own words runs past the clip's end.
        package = valid_package()
        stop(package, "#0012")["versions"][1]["words"][0]["end"] = 329.0
        self.assertBreaks(package, "P10")


def valid_answers() -> list[dict]:
    return copy.deepcopy(items("valid/answers-bg-3-37-brisbane.jsonl"))


def packages() -> dict:
    return {sha("valid/package-bg-3-37-brisbane.json"): valid_package()}


class AnswerRuleTests(unittest.TestCase):
    def assertBreaks(self, records: list[dict], rule: str):
        for record in records:
            self.assertEqual(schema_errors("review-answers", record), [])
        self.assertEqual({b.rule for b in answer_rules(records, packages())}, {rule})

    def test_a2_an_answer_that_does_not_fit_the_stop(self):
        records = valid_answers()
        # The first record answers the single-version stop #0001; a verse answer cannot fit it.
        records[0]["answer"] = {"kind": "not-a-verse"}
        self.assertBreaks(records, "A2")

    def test_a4_a_spot_check_of_a_record_that_does_not_exist(self):
        records = valid_answers()
        check = next(r for r in records if r["record"] == "spot-check")
        check["reviews"] = "00000000-0000-4000-8000-000000000000"
        self.assertBreaks(records, "A4")

    def test_a5_an_answer_changed_after_it_was_spot_checked(self):
        records = valid_answers()
        check = next(r for r in records if r["record"] == "spot-check")
        checked = next(r for r in records if r["id"] == check["reviews"])
        late = {**copy.deepcopy(checked), "id": "11111111-1111-4111-8111-111111111111",
                "supersedes": checked["id"], "answered_at": "2026-11-03T09:00:00Z"}
        self.assertBreaks(records + [late], "A5")

    def test_a6_two_records_sharing_an_id(self):
        records = valid_answers()
        records[1]["id"] = records[0]["id"]
        self.assertIn("A6", {b.rule for b in answer_rules(records, packages())})

    def test_a7_typed_text_not_in_nfc(self):
        records = valid_answers()
        records[0]["note"] = "Kṛṣṇa"
        self.assertBreaks(records, "A7")

    def test_a8_an_answer_older_than_its_package(self):
        records = valid_answers()
        records[0]["answered_at"] = "2026-10-28T00:00:00Z"
        self.assertBreaks(records, "A8")


class AcceptedAndResultsRuleTests(unittest.TestCase):
    def test_c1_a_list_naming_a_different_answers_file(self):
        accepted = items("valid/accepted-bg-3-37-brisbane.json")[0]
        accepted["answers"]["records"] += 1
        found = accepted_rules(accepted, valid_package(), sha("valid/package-bg-3-37-brisbane.json"),
                               valid_answers(), sha("valid/answers-bg-3-37-brisbane.jsonl"))
        self.assertEqual({b.rule for b in found}, {"C1"})

    def test_r1_results_that_applied_a_record_the_list_did_not_name(self):
        results = items("valid/results-bg-3-37-brisbane.json")[0]
        results["applied"] = results["applied"][1:]
        found = results_rules(results, sha("valid/package-bg-3-37-brisbane.json"), valid_answers(),
                              sha("valid/answers-bg-3-37-brisbane.jsonl"),
                              items("valid/accepted-bg-3-37-brisbane.json")[0],
                              sha("valid/accepted-bg-3-37-brisbane.json"))
        self.assertEqual({b.rule for b in found}, {"R1"})


if __name__ == "__main__":
    unittest.main()
