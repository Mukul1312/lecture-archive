"""
build_floor_set.py — assemble the REAL-speaker floor for the voice dissimilarity gate.

The gate (voice_gate.py) is uncalibrated without an answer to "what does a genuinely DIFFERENT
Indian male score against his centroid?" — caveat C2 in docs/identity-verification.md. This builds
that set from AI4Bharat Kathbath (CC0, ungated on the e2enetworks object store).

Input is a BYTE RANGE of testunk_audio.tar, not the whole 2.2 GB file — Hindi sits in one
contiguous region, so we pull ~230 MB. A range slice is truncated at both ends, so `tarfile` would
raise; we walk the 512-byte headers by hand and stop cleanly at the first unreadable one.

Kathbath filenames carry the labels we need:  <uttid>-<speakerid>-<gender>.m4a
so speaker identity and gender come free, with no metadata download.

  .venv/Scripts/python.exe scripts/hi/build_floor_set.py --range <range.bin> --per-speaker 8
"""
import argparse
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data/hi/floor_speakers"
PREFIX = b"kb_data_clean_m4a/hindi"
BLOCK = 512
sys.stdout.reconfigure(encoding="utf-8")


def find_start(buf):
    """First 512-aligned offset holding a plausible tar header for a hindi entry."""
    for off in range(0, len(buf) - BLOCK, BLOCK):
        name = buf[off:off + 100].rstrip(b"\0")
        if name.startswith(PREFIX) and buf[off + 257:off + 262] == b"ustar":
            return off
    return -1


def walk(buf, start):
    """Yield (name, payload) for each entry from `start` until the data runs out."""
    off = start
    while off + BLOCK <= len(buf):
        hdr = buf[off:off + BLOCK]
        name = hdr[:100].rstrip(b"\0")
        if not name or hdr[257:262] != b"ustar":
            break                                  # padding, or we walked off the slice
        try:
            size = int(hdr[124:136].rstrip(b"\0 ").decode() or "0", 8)
        except ValueError:
            break
        data_off = off + BLOCK
        if data_off + size > len(buf):
            break                                  # final entry truncated by the range cut
        if hdr[156:157] in (b"0", b"\0"):          # regular file
            yield name.decode("utf-8", "replace"), buf[data_off:data_off + size]
        off = data_off + ((size + BLOCK - 1) // BLOCK) * BLOCK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", required=True, help="byte-range slice of testunk_audio.tar")
    ap.add_argument("--per-speaker", type=int, default=8,
                    help="clips kept per speaker; the gate averages them into ONE score per "
                         "speaker, so >1 reduces per-clip noise without shrinking the floor SD")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found — needed to decode m4a")
    buf = Path(args.range).read_bytes()
    print(f"slice: {len(buf)/1e6:.0f} MB")

    start = find_start(buf)
    if start < 0:
        sys.exit("no hindi tar header in this range — adjust the byte offsets")
    print(f"first hindi header at +{start} bytes")

    by_spk = defaultdict(list)
    for name, payload in walk(buf, start):
        stem = Path(name).stem
        parts = stem.rsplit("-", 2)
        if len(parts) != 3:
            continue
        _, spk, gender = parts
        if gender != "m":                          # male speakers only — matches the target brief
            continue
        by_spk[spk].append((stem, payload))

    if not by_spk:
        sys.exit("walked the slice but found no male hindi clips")
    print(f"found {sum(len(v) for v in by_spk.values())} male clips "
          f"across {len(by_spk)} distinct speakers")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    tmp = OUT / "_tmp.m4a"
    kept = 0
    for spk in sorted(by_spk):
        # Longest clips first — ECAPA/d-vector get noisy under ~5 s.
        clips = sorted(by_spk[spk], key=lambda kv: len(kv[1]), reverse=True)[:args.per_speaker]
        for stem, payload in clips:
            tmp.write_bytes(payload)
            wav = OUT / f"spk{spk}__{stem}.wav"
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                                "-ac", "1", "-ar", "16000", str(wav)],
                               capture_output=True)
            if r.returncode == 0 and wav.exists():
                kept += 1
            else:
                print(f"  decode failed: {stem}")
    tmp.unlink(missing_ok=True)
    print(f"\nwrote {kept} wavs from {len(by_spk)} speakers -> {OUT.relative_to(ROOT)}")
    print("next:  scripts/hi/voice_gate.py --enc ecapa   --floor data/hi/floor_speakers")
    print("       scripts/hi/voice_gate.py --enc dvector --floor data/hi/floor_speakers")


if __name__ == "__main__":
    main()
