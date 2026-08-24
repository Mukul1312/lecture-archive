"""
enhance_part_multi.py — full-part render using the multi-DFN blend (option "B").

WHY THIS EXISTS. On the 5-minute ladder, blending two parallel DeepFilterNet renders — the accepted
--atten-lim 24 through all speech, full strength only inside guarded pauses — measured:

    13_dfn_atten24              22.4 dB noise cut, d-vector cos 0.8310   (shipped)
    16_multi_dfn24_full_pauses  33.4 dB noise cut, d-vector cos 0.8294   <- 11 dB more, same identity

It is the only thing tested that beat the suppression-vs-identity curve rather than moving along it,
and it does so for a simple reason: the extra attenuation is applied where there is no voice to
damage. The speech samples are byte-identical to the render already vetted by the Odia listener.

ALIGNMENT — the reason this does not just call enhance_multi_dfn.py on the finished files.
Blending needs original, speech-render and pause-render to be sample-aligned. Our stitch overlaps a
30 ms crossfade at each of 27 joins, so the stitched output is ~0.81 s SHORTER than the raw input,
and the drift accumulates across the file. Detecting pauses from the raw while blending the stitched
renders would misalign progressively worse toward the end. So we blend PER CHUNK, before stitching,
where all three signals are exactly the same length.

Reuses enhance_part.py (chunking, memory-adaptive DFN, stitch, loudnorm, encode) and
enhance_multi_dfn.py (the guarded pause mask) rather than reimplementing either.

RUN: .venv/Scripts/python.exe scripts/enhance_part_multi.py data/enhance/jiva_goswami/part-01.mp3
"""
import argparse
import gc
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import enhance_part as ep                       # noqa: E402
from enhance_multi_dfn import guarded_pause_mask  # noqa: E402

SR = ep.SR

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--atten", type=int, default=24, help="attenuation used through speech")
    ap.add_argument("--lufs", type=float, default=-16.0)
    a = ap.parse_args()

    src = Path(a.src)
    stem = src.stem
    work = ep.OUT / stem / "_work"
    work.mkdir(parents=True, exist_ok=True)
    out_dir = ep.OUT / stem
    final_flac = out_dir / f"{stem}-enhanced-multi.flac"
    final_mp3 = out_dir / f"{stem}-enhanced-multi.mp3"
    t0 = time.time()

    print(f"\n{'='*76}\n{stem} — multi-DFN: atten{a.atten} through speech, FULL inside pauses\n{'='*76}")

    print("\n[0] DECODE")
    raw = work / "00_raw.wav"
    if raw.exists():
        y, _ = sf.read(str(raw), dtype="float32")
        print(f"  reusing {raw.name} ({len(y)/SR/60:.1f} min)")
    else:
        y = ep.decode_headroom(src)
        sf.write(str(raw), y, SR)

    print("\n[1] SPLIT at silence (same boundaries as the single-render run)")
    cuts = ep.silence_cuts(y)
    bounds = [0] + cuts + [len(y)]
    chunks = []
    for i in range(len(bounds) - 1):
        p = work / f"10_chunk{i:02d}.wav"
        if not p.exists():
            sf.write(str(p), y[bounds[i]:bounds[i+1]], SR)
        chunks.append(p)
    print(f"  {len(chunks)} chunks")
    del y
    gc.collect()

    print(f"\n[2a] SPEECH RENDER  (--atten-lim {a.atten})  — cached from the earlier run")
    speech_r = []
    for i, c in enumerate(chunks):
        dst = work / f"20_enh{i:02d}.wav"
        if not dst.exists():
            ts = time.time()
            ep.enhance_chunk(c, dst, a.atten, work, f"s{i:02d}")
            print(f"  chunk {i+1}/{len(chunks)} rendered in {time.time()-ts:.0f}s")
        speech_r.append(dst)
    print(f"  {sum(1 for p in speech_r if p.exists())}/{len(chunks)} present")

    print("\n[2b] PAUSE RENDER  (full strength, no attenuation limit)")
    pause_r = []
    for i, c in enumerate(chunks):
        dst = work / f"21_full{i:02d}.wav"
        if dst.exists():
            print(f"  chunk {i+1}/{len(chunks)}  cached")
        else:
            ts = time.time()
            ep.enhance_chunk(c, dst, None, work, f"f{i:02d}")
            dur = sf.info(str(c)).duration
            print(f"  chunk {i+1}/{len(chunks)}  {dur/60:.1f} min in {time.time()-ts:.0f}s")
        pause_r.append(dst)

    print("\n[3] BLEND per chunk (guarded pauses only)")
    blended, occ = [], []
    for i, c in enumerate(chunks):
        dst = work / f"22_multi{i:02d}.wav"
        if not dst.exists():
            orig, _ = sf.read(str(c), dtype="float32")
            sp, _ = sf.read(str(speech_r[i]), dtype="float32")
            pa, _ = sf.read(str(pause_r[i]), dtype="float32")
            n = min(len(orig), len(sp), len(pa))
            orig, sp, pa = orig[:n], sp[:n], pa[:n]
            mask, _, regions = guarded_pause_mask(orig, SR, 20.0, 500.0, 250.0, 120.0)
            out = sp * (1.0 - mask) + pa * mask
            sf.write(str(dst), out.astype("float32"), SR)
            occ.append(100 * float(np.mean(mask > 0.5)))
        blended.append(dst)
    if occ:
        print(f"  strong-render occupancy: {np.mean(occ):.1f}% of samples (mean over chunks)")
    else:
        print("  reusing cached blends")

    print("\n[4] STITCH")
    out = ep.stitch(blended)
    print(f"  {len(out)/SR/60:.1f} min, {ep.XFADE_MS} ms crossfades at {len(blended)-1} joins")

    print(f"\n[5] NORMALISE to {a.lufs} LUFS")
    stitched = work / "30_stitched_multi.wav"
    sf.write(str(stitched), out, SR)
    del out
    gc.collect()
    tmp = work / "40_final_multi.wav"
    out = ep.normalise(stitched, tmp, a.lufs)
    ep.report("multi", out)

    print("\n[6] ENCODE")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                    "-sample_fmt", "s16", str(final_flac)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-b:a", "128k",
                    str(final_mp3)], check=True)
    print(f"  {final_flac.name}  {final_flac.stat().st_size/1e6:.1f} MB")
    print(f"  {final_mp3.name}  {final_mp3.stat().st_size/1e6:.1f} MB")
    print(f"\ndone in {(time.time()-t0)/60:.1f} min -> {out_dir}")


if __name__ == "__main__":
    main()
