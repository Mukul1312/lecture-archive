"""The review format this repository publishes, and the rules a schema cannot check.

`contracts/review/` holds four JSON Schemas (Draft 2020-12) and their golden examples. They are
the agreement with the review app (`review-assistance`): this repository publishes a lecture
review package, the app sends back answer records and its list of the answers that count, and
this repository publishes results. The producer owns the format (ADR-0016); the app keeps a
pinned copy and checks the same examples in TypeScript.

JSON Schema checks each field on its own. It cannot say that a clip covers its stop, that a
record matches the package it names, or that a list accounts for every stop, so those rules are
here, each under the stable id the format's README gives it. The app implements the same rules
in `src/contract/*Rules.ts`; where the README is silent, these follow that code, so the two
sides cannot disagree about a file without one of them being wrong.

A file that breaks a rule is refused. Nothing here repairs one.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "contracts/review"

# The newest minor version of each format this reader understands. A newer minor only adds
# fields or values, but every object lists all of its fields, so an old reader would refuse the
# new field anyway - better to say why (agreed 29 October 2026: update the reader first).
KNOWN = {
    "lecture-review-package": (1, 0),
    "review-answers": (1, 0),
    "accepted-answers": (1, 0),
    "review-results": (0, 1),
}

# Answer kinds that give this repository text or a marking to apply; the rest close a stop or
# send it back for a decision. The same set as the app's APPLIED_KINDS.
APPLIED = frozenset({"chose-version", "both-right", "confirmed", "typed-fix", "not-lecturer",
                     "verse-confirmed"})

# Which answers fit which kind of stop: the README's "Kinds of stop" table.
FITS = {
    "word-disagreement": {"chose-version", "both-right", "typed-fix", "cant-tell", "not-lecturer",
                          "dont-know-language", "escalated"},
    "single-version": {"confirmed", "typed-fix", "cant-tell", "not-lecturer",
                       "dont-know-language", "escalated"},
    "agreement-sample": {"confirmed", "typed-fix", "cant-tell", "not-lecturer",
                         "dont-know-language", "escalated"},
    "verse-check": {"verse-confirmed", "verse-different", "not-a-verse", "cant-tell",
                    "not-lecturer", "dont-know-language", "escalated"},
}


@dataclass(frozen=True)
class RuleBreak:
    rule: str
    message: str


@lru_cache(maxsize=None)
def validator(kind: str) -> Draft202012Validator:
    schema = json.loads((CONTRACT / f"{kind}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(kind: str, item) -> list[str]:
    """Every way `item` fails its schema, in plain words, or nothing."""
    return [f"{'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}"
            for e in validator(kind).iter_errors(item)]


def refuse_unknown_version(kind: str, item: dict) -> None:
    """Raise if `item` is a newer version of its format than this reader understands."""
    name, _, version = item.get("schema", "").partition("/")
    major, _, minor = version.partition(".")
    if name != kind or not (major.isdigit() and minor.isdigit()):
        raise ValueError(f"not a {kind} file: schema is {item.get('schema')!r}")
    known_major, known_minor = KNOWN[kind]
    if int(major) != known_major or int(minor) > known_minor:
        raise ValueError(f"{item['schema']} is newer than this reader understands "
                         f"({kind}/{known_major}.{known_minor}); update the reader first")


def read_items(path: Path) -> list:
    """A JSON file as one item, or a JSON Lines file as one item per line."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.split("\n") if line.strip()]
    return [json.loads(text)]


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _strings(value):
    """Every string in a parsed JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


def _nfc(text: str) -> bool:
    return unicodedata.normalize("NFC", text) == text


def package_rules(package: dict) -> list[RuleBreak]:
    """Rules P1-P10 for one lecture review package. Empty means it passes."""
    found: list[RuleBreak] = []

    def add(rule: str, message: str) -> None:
        found.append(RuleBreak(rule, message))

    duration = package["lecture"]["duration_seconds"]
    lecture = package["lecture"]["id"]

    def inside(where: str, *times) -> None:
        for t in times:
            if t is not None and not 0 <= t <= duration:
                add("P1", f"{where}: {t} s is outside the recording (0 to {duration} s)")

    def forwards(where: str, interval: dict) -> None:
        if not interval["start"] < interval["end"]:
            add("P2", f"{where}: starts at {interval['start']} s but ends at {interval['end']} s")

    def word_times(where: str, word: dict, source: str) -> None:
        start, end = word["start"], word["end"]
        if (start is None) != (end is None):
            add("P2", f"{where}: only one of start and end is missing")
        elif start is not None and start > end:
            add("P2", f"{where}: the word runs backwards")
        elif start is None and source != "published":
            add("P2", f"{where}: untimed, but only a published word may be left unplaced")
        inside(where, start, end)

    for name in ("trustworthy_spans", "untranscribed"):
        intervals = package[name]
        for i, interval in enumerate(intervals):
            inside(f"{name}[{i}]", interval["start"], interval["end"])
            forwards(f"{name}[{i}]", interval)
        for i in range(1, len(intervals)):
            if intervals[i]["start"] < intervals[i - 1]["end"]:
                add("P4", f"{name}[{i}] is out of order or overlaps the one before")
    for gap in package["untranscribed"]:
        for span in package["trustworthy_spans"]:
            if gap["start"] < span["end"] and span["start"] < gap["end"]:
                add("P4", f"untranscribed {gap['start']}-{gap['end']} s overlaps a trustworthy span")

    if package["package"]["id"] != f"{lecture}/v{package['package']['version']}":
        add("P5", f"package id {package['package']['id']} does not match the lecture and version")
    ids: set[str] = set()
    for stop in package["stops"]:
        name = stop["id"]
        if name in ids:
            add("P5", f"{name}: appears twice")
        ids.add(name)
        if not name.startswith(f"{lecture}#"):
            add("P5", f"{name}: is not a stop of {lecture}")
        clip = stop["context"]
        inside(name, stop["start"], stop["end"], clip["start"], clip["end"])
        forwards(name, stop)
        forwards(f"{name} clip", clip)
        if not (clip["start"] <= stop["start"] and stop["end"] <= clip["end"]):
            add("P3", f"{name}: the clip does not cover the stop")
        sources = [v["source"] for v in stop["versions"]]
        if len(set(sources)) != len(sources):
            add("P7", f"{name}: two versions from one source")
        for version in stop["versions"]:
            for position in version["differs"]:
                if position >= len(version["words"]):
                    add("P7", f"{name}: differing position {position} is beyond its "
                              f"{len(version['words'])} words")
            for i, word in enumerate(version["words"]):
                word_times(f"{name} {version['source']} word {i}", word, version["source"])
                if word["start"] is not None and word["end"] is not None and not (
                        clip["start"] <= word["start"] and word["end"] <= clip["end"]):
                    add("P10", f"{name}: word {word['text']!r} lies outside the clip")
        texts = [[w["text"] for w in v["words"]] for v in stop["versions"]]
        if stop["kind"] == "agreement-sample" and any(t != texts[0] for t in texts):
            add("P7", f"{name}: agreement sample versions differ")
        if stop["kind"] == "word-disagreement" and all(t == texts[0] for t in texts):
            add("P7", f"{name}: word disagreement versions are the same")
        verse = stop.get("verse")
        if verse and any(i >= len(verse["printed_words"]) for i in verse["recited"]):
            add("P8", f"{name}: a recited position is beyond the printed words")
    for a, b in zip(package["stops"], package["stops"][1:]):
        if (b["start"], b["end"]) < (a["start"], a["end"]):
            add("P4", f"stops are not in timeline order at {b['id']}")

    last = None
    for i, word in enumerate(package["transcript"]["words"]):
        word_times(f"transcript word {i}", word, word["source"])
        if word["stop"] is not None and word["stop"] not in ids:
            add("P5", f"transcript word {i} names a stop that does not exist")
        if word["start"] is not None:
            if last is not None and word["start"] < last:
                add("P4", f"transcript word {i} is out of time order")
            last = word["start"]

    original = package["audio"]["original"]
    if original["object"] != f"audio/{original['sha256']}.mp3":
        add("P6", "the original's object name does not match its hash")
    copy = package["audio"]["listening_copy"]
    if copy is not None:
        if copy["object"] != f"listen/{original['sha256']}-cbr128.mp3":
            add("P6", "the listening copy's name does not match the original's hash")
        if abs(copy["seconds"] - duration) > 0.05:
            add("P6", "the listening copy's length is more than 0.05 s from the original's")

    for text in _strings(package):
        if not _nfc(text):
            add("P9", f"not in Unicode NFC: {text!r}")
    return found


def answer_rules(records: list[dict], packages: dict[str, dict]) -> list[RuleBreak]:
    """Rules A1-A9 for an answers file.

    `packages` maps each package file's SHA-256 to the package. A record carried over from an
    earlier version of the lecture's package is checked against the version it was given on.
    """
    found: list[RuleBreak] = []

    def add(rule: str, record: dict, message: str) -> None:
        found.append(RuleBreak(rule, f"{record['id']}: {message}"))

    by_id: dict[str, dict] = {}
    for record in records:
        if record["id"] in by_id:
            add("A6", record, "two records share this id")
        by_id[record["id"]] = record

        package = packages.get(record["package"]["sha256"])
        if (package is None or package["package"]["id"] != record["package"]["id"]
                or package["package"]["version"] != record["package"]["version"]):
            add("A1", record, "does not match the package it names")
            continue
        stop = next((s for s in package["stops"] if s["id"] == record["stop"]), None)
        if stop is None:
            add("A1", record, "names a stop that is not in its package")
            continue
        if record["lecture"] != package["lecture"]["id"]:
            add("A1", record, "names a different lecture")
        if record["audio_sha256"] != package["audio"]["original"]["sha256"]:
            add("A1", record, "names different audio")
        if (record["interval"]["start"], record["interval"]["end"]) != (stop["start"], stop["end"]):
            add("A1", record, "its interval is not the stop's")

        sources = {v["source"] for v in stop["versions"]}
        if any(s not in sources for s in record["shown_order"]):
            add("A2", record, "shown_order names a source the stop does not have")
        if (record["record"] == "answer" and stop["kind"] == "word-disagreement"
                and len(record["shown_order"]) != len(sources)):
            add("A2", record, "a word disagreement was answered without seeing every version")
        answer = record.get("answer")
        if answer:
            if answer["kind"] not in FITS[stop["kind"]]:
                add("A2", record, f"{answer['kind']} does not fit a {stop['kind']} stop")
            if "chosen_source" in answer and answer["chosen_source"] not in sources:
                add("A2", record, "the chosen source is not one of the stop's")
            printed = len(stop.get("verse", {}).get("printed_words", []))
            if any(i >= printed for i in answer.get("recited", [])):
                add("A2", record, "a recited position is beyond the printed words")
            for key in ("typed_text", "other_reference"):
                if key in answer and not _nfc(answer[key]):
                    add("A7", record, f"{key} is not in Unicode NFC")
        if "note" in record and not _nfc(record["note"]):
            add("A7", record, "the note is not in Unicode NFC")
        if record.get("spoken_language") == stop["language"]:
            add("A9", record, "spoken_language repeats the stop's own language")
        if _time(record["answered_at"]) < _time(package["package"]["published_at"]):
            add("A8", record, "is earlier than its package")

    superseded_by: dict[str, dict] = {}
    for record in records:
        if record["supersedes"] is None:
            continue
        old = by_id.get(record["supersedes"])
        if old is None:
            add("A3", record, "supersedes a record that does not exist")
            continue
        if (old["by"]["id"] != record["by"]["id"] or old["stop"] != record["stop"]
                or old["record"] != record["record"]
                or not _time(old["answered_at"]) < _time(record["answered_at"])):
            add("A3", record, "supersedes a record that is not the same person's earlier "
                              "record for this stop")
        if old["id"] in superseded_by:
            add("A3", record, "supersedes a record that was already superseded")
        superseded_by[old["id"]] = record

    for record in records:
        if "reviews" not in record:
            continue
        old = by_id.get(record["reviews"])
        if (old is None or old["stop"] != record["stop"]
                or not _time(old["answered_at"]) < _time(record["answered_at"])):
            add("A4", record, "reviews a missing, later or other-stop record")
            continue
        if record["record"] == "spot-check" and old["record"] != "answer":
            add("A4", record, "spot-checks something other than an answer")
        if record["record"] == "adjudication" and not (
                old["record"] == "answer" or (old["record"] == "adjudication"
                                              and old.get("answer", {}).get("kind") == "escalated")):
            add("A4", record, "settles something other than an answer or an escalation")
        newer = superseded_by.get(old["id"])
        if (newer is not None and newer["record"] == "answer"
                and _time(record["answered_at"]) < _time(newer["answered_at"])):
            add("A5", newer, "changes an answer after it was settled or spot-checked")
    return found


def accepted_rules(accepted: dict, package: dict, package_sha: str, records: list[dict],
                   answers_sha: str) -> list[RuleBreak]:
    """Rules C1-C3: the app's list of the answers that count is complete and consistent.

    Whether the app chose the right record is for the app's own tests; this repository applies
    the list and never works it out again (agreed 29 October 2026).
    """
    found: list[RuleBreak] = []
    if (accepted["lecture"] != package["lecture"]["id"]
            or accepted["package"]["sha256"] != package_sha
            or accepted["package"]["id"] != package["package"]["id"]
            or accepted["package"]["version"] != package["package"]["version"]):
        found.append(RuleBreak("C1", "the lecture or package does not match"))
    if accepted["answers"]["sha256"] != answers_sha or accepted["answers"]["records"] != len(records):
        found.append(RuleBreak("C1", "the answers file's hash or record count does not match"))

    if [e["stop"] for e in accepted["stops"]] != [s["id"] for s in package["stops"]]:
        found.append(RuleBreak("C2", "stops are missing, repeated, extra or out of the "
                                     "package's order"))

    by_id = {r["id"]: r for r in records}
    replaced = {r["supersedes"] for r in records if r["supersedes"]}
    for entry in accepted["stops"]:
        if entry["record"] is None:
            continue
        record = by_id.get(entry["record"])
        if record is None or record["stop"] != entry["stop"] or record["id"] in replaced:
            found.append(RuleBreak("C3", f"{entry['stop']}: names a missing, other-stop or "
                                         f"replaced record"))
    return found


def results_rules(results: dict, package_sha: str, records: list[dict], answers_sha: str,
                  accepted: dict, accepted_sha: str) -> list[RuleBreak]:
    """Rule R1: the results applied exactly the records the app's list names that give text."""
    found: list[RuleBreak] = []
    by_id = {r["id"]: r for r in records}
    expected = [{"stop": e["stop"], "record": e["record"]} for e in accepted["stops"]
                if e["record"] and by_id.get(e["record"], {}).get("answer", {}).get("kind") in APPLIED]
    if results["applied"] != expected:
        found.append(RuleBreak("R1", "applied does not match the app's list"))
    if (results["package"]["sha256"] != package_sha
            or results["imported"]["answers"]["sha256"] != answers_sha
            or results["imported"]["accepted"]["sha256"] != accepted_sha):
        found.append(RuleBreak("R1", "a package, answers or list hash does not match"))
    return found
