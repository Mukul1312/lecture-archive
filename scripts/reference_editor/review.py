"""Pure logic for the local reference editor.

The editor turns one subtitle file into a reviewable state: the owner listens,
corrects each cue's words and marks it checked. Timings and the original words
come from the source file and can never be changed through the editor, so a
saved review always traces back to exactly the subtitles it started from.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import math
import re


SCHEMA = "reference-review/1"
STATUSES = ("unchecked", "ok", "fixed", "unsure")
MAX_TEXT_CHARS = 5_000
MAX_NOTE_CHARS = 2_000
MAX_SESSION_NOTES_CHARS = 20_000
MAX_OFFSET_MS = 60_000
NO_SPEECH = "[no speech]"

_TIME = re.compile(r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})")
# Only SubRip's own formatting tags; transcriber markers such as "<inaudible>" are words.
_FORMAT_TAG = re.compile(r"</?(?:b|i|u|font)\b[^>]*>", re.IGNORECASE)
_IMMUTABLE_CUE_FIELDS = ("n", "start_ms", "end_ms", "original")


class ReviewError(ValueError):
    """A subtitle file or a submitted review that the editor must not accept."""


@dataclass(frozen=True)
class Cue:
    number: int
    start_ms: int
    end_ms: int
    raw: str


def parse_time(value: str) -> int:
    match = _TIME.fullmatch(value.strip())
    if not match:
        raise ReviewError(f"invalid subtitle time: {value!r}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    if minutes > 59 or seconds > 59:
        raise ReviewError(f"invalid subtitle time: {value!r}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def format_time(ms: int) -> str:
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(text: str) -> list[Cue]:
    normalized = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ReviewError("subtitle file has no cues")
    cues: list[Cue] = []
    for block in re.split(r"\n[ \t]*\n", normalized):
        lines = block.split("\n")
        expected = len(cues) + 1
        if len(lines) < 2 or "-->" not in lines[1]:
            raise ReviewError(f"malformed cue block near cue {expected}")
        try:
            number = int(lines[0].strip())
        except ValueError:
            raise ReviewError(f"cue number is not an integer: {lines[0]!r}") from None
        if number != expected:
            raise ReviewError(f"cue {number} is out of sequence; expected {expected}")
        start_text, _, end_text = lines[1].partition("-->")
        end_fields = end_text.split()
        start = parse_time(start_text)
        end = parse_time(end_fields[0] if end_fields else "")
        if end < start:
            raise ReviewError(f"cue {number} ends before it starts")
        if cues and start < cues[-1].start_ms:
            raise ReviewError(f"cue {number} starts before cue {number - 1}")
        cues.append(Cue(number, start, end, "\n".join(lines[2:])))
    return cues


def plain_text(raw: str) -> str:
    lines = (html.unescape(_FORMAT_TAG.sub("", line)).strip() for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)


def source_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_review(srt_bytes: bytes, *, source_name: str, audio: str) -> dict:
    try:
        text = srt_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReviewError("subtitle file is not UTF-8") from error
    return {
        "schema": SCHEMA,
        "source_srt": source_name,
        "source_srt_sha256": source_digest(srt_bytes),
        "audio": audio,
        "offset_ms": 0,
        "last_position_s": 0.0,
        "session_notes": "",
        "cues": [
            {
                "n": cue.number,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "original": plain_text(cue.raw),
                "text": plain_text(cue.raw),
                "status": "unchecked",
                "note": "",
            }
            for cue in parse_srt(text)
        ],
    }


def validate_review(submitted: object, *, baseline: dict) -> dict:
    """Return a clean copy of a submitted review, or raise if it must not be saved.

    Only the words, statuses, notes, the listening offset and the resume position
    may differ from the baseline built from the subtitle file.
    """
    if not isinstance(submitted, dict):
        raise ReviewError("review must be a JSON object")
    if submitted.get("schema") != SCHEMA:
        raise ReviewError("unsupported review schema")
    if submitted.get("source_srt_sha256") != baseline["source_srt_sha256"]:
        raise ReviewError("review belongs to a different subtitle file")
    cues = submitted.get("cues")
    if not isinstance(cues, list) or len(cues) != len(baseline["cues"]):
        raise ReviewError("review must contain exactly one entry per subtitle cue")

    clean_cues = []
    for given, base in zip(cues, baseline["cues"]):
        label = f"cue {base['n']}"
        if not isinstance(given, dict):
            raise ReviewError(f"{label} must be an object")
        for key in _IMMUTABLE_CUE_FIELDS:
            if given.get(key) != base[key]:
                raise ReviewError(f"{label}: {key} cannot be changed")
        text = _bounded_text(given.get("text"), MAX_TEXT_CHARS, f"{label} text")
        note = _bounded_text(given.get("note", ""), MAX_NOTE_CHARS, f"{label} note")
        status = given.get("status")
        if status not in STATUSES:
            raise ReviewError(f"{label}: unknown status {status!r}")
        if status in ("ok", "fixed"):
            status = "fixed" if text != base["original"] else "ok"
        clean_cues.append({**base, "text": text, "status": status, "note": note})

    offset = submitted.get("offset_ms", 0)
    if not isinstance(offset, int) or isinstance(offset, bool) or abs(offset) > MAX_OFFSET_MS:
        raise ReviewError(f"offset_ms must be an integer within ±{MAX_OFFSET_MS}")
    position = submitted.get("last_position_s", 0.0)
    if (not isinstance(position, (int, float)) or isinstance(position, bool)
            or not math.isfinite(position) or not 0 <= position < 1_000_000):
        raise ReviewError("last_position_s must be a non-negative number of seconds")
    notes = _bounded_text(submitted.get("session_notes", ""), MAX_SESSION_NOTES_CHARS, "session notes")

    return {
        "schema": SCHEMA,
        "source_srt": baseline["source_srt"],
        "source_srt_sha256": baseline["source_srt_sha256"],
        "audio": baseline["audio"],
        "offset_ms": offset,
        "last_position_s": float(position),
        "session_notes": notes,
        "cues": clean_cues,
    }


def carry_over(previous: object, baseline: dict) -> tuple[dict, list[int]]:
    """Move a listener's work onto a re-timed copy of the same subtitles.

    Words, status and notes transfer for every cue whose number and original words
    are unchanged; timings come from the new baseline. The listening offset resets,
    because re-timing replaces it. Returns the new review and the cue numbers that
    could not be carried.
    """
    if not isinstance(previous, dict) or previous.get("schema") != SCHEMA:
        raise ReviewError("the previous review is not a reference review")
    earlier = {cue.get("n"): cue for cue in previous.get("cues") or [] if isinstance(cue, dict)}
    draft = {**baseline, "cues": [dict(cue) for cue in baseline["cues"]]}
    skipped = []
    for cue in draft["cues"]:
        before = earlier.get(cue["n"])
        if before is None or before.get("original") != cue["original"]:
            skipped.append(cue["n"])
            continue
        cue.update(text=before.get("text"), status=before.get("status"), note=before.get("note", ""))
    draft["session_notes"] = previous.get("session_notes", "")
    draft["last_position_s"] = previous.get("last_position_s", 0.0)
    return validate_review(draft, baseline=baseline), skipped


def counts(review: dict) -> dict[str, int]:
    tally = {status: 0 for status in STATUSES}
    for cue in review["cues"]:
        tally[cue["status"]] += 1
    return {"total": len(review["cues"]), "checked": tally["ok"] + tally["fixed"], **tally}


def export_srt(review: dict) -> str:
    """SubRip text with the corrected words and the source's original timings."""
    blocks = []
    for cue in review["cues"]:
        text = "\n".join(line.strip() for line in cue["text"].split("\n") if line.strip()) or NO_SPEECH
        blocks.append(f"{cue['n']}\n{format_time(cue['start_ms'])} --> {format_time(cue['end_ms'])}\n{text}")
    return ("\n\n".join(blocks) + "\n").replace("\n", "\r\n")


def change_log(review: dict) -> str:
    tally = counts(review)
    lines = [
        f"# Reference review: {review['source_srt']}",
        "",
        f"- Source SHA-256: `{review['source_srt_sha256']}`",
        f"- Audio: {review['audio']}",
        f"- Checked {tally['checked']} of {tally['total']} cues: {tally['ok']} unchanged, "
        f"{tally['fixed']} corrected. {tally['unsure']} unsure, {tally['unchecked']} not yet checked.",
        "",
    ]
    if review["session_notes"].strip():
        lines += ["## Session notes", "", review["session_notes"].strip(), ""]
    lines += ["## Corrected, unsure or annotated cues", ""]
    listed = 0
    for cue in review["cues"]:
        changed = cue["text"] != cue["original"]
        if not (changed or cue["status"] == "unsure" or cue["note"].strip()):
            continue
        listed += 1
        lines += [f"### Cue {cue['n']} · {format_time(cue['start_ms'])[:8]} · {cue['status']}", ""]
        lines.append(f"- Subtitle: {_one_line(cue['original'])}")
        if changed:
            lines.append(f"- Corrected: {_one_line(cue['text'])}")
        if cue["note"].strip():
            lines.append(f"- Note: {_one_line(cue['note'])}")
        lines.append("")
    if not listed:
        lines += ["None yet.", ""]
    return "\n".join(lines)


def _bounded_text(value: object, limit: int, label: str) -> str:
    if not isinstance(value, str):
        raise ReviewError(f"{label} must be text")
    value = value.replace("\r\n", "\n")
    if len(value) > limit:
        raise ReviewError(f"{label} is longer than {limit} characters")
    return value


def _one_line(text: str) -> str:
    return " / ".join(line.strip() for line in text.split("\n") if line.strip()) or "(empty)"
