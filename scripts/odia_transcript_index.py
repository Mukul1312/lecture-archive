"""odia_transcript_index.py — fingerprint Odia lectures and their transcripts.

Fills two columns for the tracking spreadsheet: the SHA-256 of each source audio
file and of its transcript. The spreadsheet stays the boss; this only computes
what a spreadsheet cannot, and writes a CSV to paste in.

What the fingerprints buy:

  * A transcript that changed after it was checked stops being invisible. Record
    the fingerprint when the transcript is audited; if it no longer matches, the
    file was edited, re-saved or overwritten since.
  * The same lecture transcribed twice is caught by audio fingerprint rather
    than by filename. 1,357 files with near-identical names make that a real
    risk; a re-download under a slightly different name is not.
  * A transcript that stopped being valid UTF-8 is reported outright. Odia is
    entirely non-ASCII, so an encoding accident destroys the text silently and
    is only noticed by a reader.

Audio and transcript are paired by filename stem: `<name>.mp3` with `<name>.txt`.
Anything unpaired is listed rather than dropped, so nothing goes missing quietly.

Digests are lowercase, matching every other digest in this repository.

RUN:
    python scripts/odia_transcript_index.py --audio DIR --transcripts DIR --out index.csv

    # flag transcripts that changed since the last run
    python scripts/odia_transcript_index.py --audio DIR --transcripts DIR \
        --out index.csv --previous index.csv

Standard library only, so it runs under any interpreter on the machine.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".opus", ".flac", ".ogg"}
TRANSCRIPT_SUFFIXES = {".txt", ".md", ".json", ".srt", ".vtt"}
COLUMNS = [
    "lecture", "audio_file", "audio_sha256",
    "transcript_file", "transcript_sha256", "transcript_chars", "note",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def collect(directory: Path, suffixes: set[str]) -> dict[str, Path]:
    """Map filename stem to path, for files whose suffix is one we expect."""
    found: dict[str, Path] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            found.setdefault(path.stem, path)
    return found


def transcript_measure(path: Path) -> tuple[str, str]:
    """Return (character count, note). Invalid UTF-8 is reported, never guessed."""
    raw = path.read_bytes()
    try:
        return str(len(raw.decode("utf-8"))), ""
    except UnicodeDecodeError:
        return "", "NOT VALID UTF-8 — transcript is damaged"


def previous_transcript_digests(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["lecture"]: row["transcript_sha256"]
            for row in csv.DictReader(handle)
            if row.get("transcript_sha256")
        }


def build_rows(audio_dir: Path, transcript_dir: Path, previous: dict[str, str]) -> list[dict[str, str]]:
    audio = collect(audio_dir, AUDIO_SUFFIXES)
    transcripts = collect(transcript_dir, TRANSCRIPT_SUFFIXES)

    rows: list[dict[str, str]] = []
    seen_audio: dict[str, str] = {}
    for stem in sorted(set(audio) | set(transcripts)):
        notes: list[str] = []
        audio_path, transcript_path = audio.get(stem), transcripts.get(stem)

        audio_digest = ""
        if audio_path is None:
            notes.append("no audio for this transcript")
        else:
            audio_digest = sha256_file(audio_path)
            first = seen_audio.setdefault(audio_digest, stem)
            if first != stem:
                notes.append(f"same audio as {first}")

        transcript_digest = chars = ""
        if transcript_path is None:
            notes.append("not transcribed yet")
        else:
            transcript_digest = sha256_file(transcript_path)
            chars, encoding_note = transcript_measure(transcript_path)
            if encoding_note:
                notes.append(encoding_note)
            was = previous.get(stem)
            if was and was != transcript_digest:
                notes.append("transcript CHANGED since the last index")

        rows.append({
            "lecture": stem,
            "audio_file": audio_path.name if audio_path else "",
            "audio_sha256": audio_digest,
            "transcript_file": transcript_path.name if transcript_path else "",
            "transcript_sha256": transcript_digest,
            "transcript_chars": chars,
            "note": "; ".join(notes),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audio", required=True, type=Path, help="folder of source lecture audio")
    parser.add_argument("--transcripts", required=True, type=Path, help="folder of transcripts")
    parser.add_argument("--out", required=True, type=Path, help="CSV to write")
    parser.add_argument("--previous", type=Path, help="an earlier CSV, to flag changed transcripts")
    arguments = parser.parse_args()

    for label, directory in (("audio", arguments.audio), ("transcripts", arguments.transcripts)):
        if not directory.is_dir():
            parser.error(f"{label} folder does not exist: {directory}")

    previous: dict[str, str] = {}
    if arguments.previous:
        if not arguments.previous.is_file():
            parser.error(f"previous index does not exist: {arguments.previous}")
        previous = previous_transcript_digests(arguments.previous)

    rows = build_rows(arguments.audio, arguments.transcripts, previous)
    # newline="" is required or csv doubles the line endings on Windows.
    with arguments.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    transcribed = sum(1 for row in rows if row["transcript_sha256"])
    flagged = [row for row in rows if row["note"]]
    print(f"{arguments.out}: {len(rows)} lectures, {transcribed} transcribed")
    if flagged:
        print(f"{len(flagged)} need attention:")
        for row in flagged:
            print(f"  {row['lecture'][:60]:<60} {row['note']}")
    else:
        print("nothing flagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
