"""
enhance_part.py — production pipeline: one full lecture part, end to end.

SETTING LOCKED 2026-08-02: DeepFilterNet3 with --atten-lim 24 (~22.4 dB noise reduction).
Chosen by Mukul after a blind ladder test. Two humans drove that choice, not a metric:
he accepted the voice character by ear, and an Odia-speaking listener picked this level in one
passage. The same listener later reported word-cutting at this setting; Mukul accepted that
trade-off knowingly. Worth a spot-check of the output before committing the remaining parts.

Stages, in the "deepest damage first" order the restoration literature converges on
(docs/enhance-analysis-methodology-research-2026-07-31.md):

  0 DECODE     float32, NO clamping. 64 kbps MP3 decodes ABOVE full scale (peaks to 1.86 in this
               source); clamping there destroys real peaks and manufactures flat-topped "clipping".
               We scale to 0.95 instead, so nothing is lost.
  1 SPLIT      cut into ~4 min chunks AT SILENCE. A 110-min file at 48 kHz float is ~1.3 GB in RAM
               and DeepFilterNet loads whole files; chunking keeps memory sane. Cutting inside
               pauses means the joins are inaudible without needing crossfade tricks.
  2 ENHANCE    DeepFilterNet3, --atten-lim 24. Chunks that the CPU allocator refuses are bisected
               at silence and retried — free RAM varies with whatever else is running, so adapting
               beats guessing a fixed size (and preserves the cache).
  3 STITCH     concatenate, with a short equal-power crossfade at each join as belt-and-braces.
  4 NORMALISE  EBU R128 to -16 LUFS via ffmpeg loudnorm, two-pass. NOT naive gain: lecture speech
               has a high crest factor, so plain gain overshoots full scale and peak-protection
               then cancels the loudness change (a first attempt landed at -24.6 instead of -16).
               loudnorm limits the overshooting peaks so the body reaches target.
               LAST, per the standard order: normalising earlier would just amplify the noise.
  5 ENCODE     FLAC (lossless archive) + MP3 128k (distribution; source is band-limited to
               ~7.7 kHz mono, so 128k is transparent and a higher rate just stores encoder noise).

Skips stages whose output already exists, so a re-run resumes rather than redoing everything.

RUN: .venv/Scripts/python.exe scripts/enhance_part.py data/enhance/jiva_goswami/part-01.mp3
     .venv/Scripts/python.exe scripts/enhance_part.py <mp3> --atten 24 --lufs -16
"""
import argparse
import gc
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/enhance/out"
DFN = str(ROOT / ".venv/Scripts/deepFilter.exe")
SR = 48000


def _tool(name):
    """Resolve ffmpeg/ffprobe. Installed via WinGet and NOT reliably on PATH in every shell this
    runs from — falling back to the known install location beats failing mid-pipeline."""
    found = shutil.which(name)
    if found:
        return found
    base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    if base.exists():
        hits = sorted(base.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"))
        if hits:
            return str(hits[0])
    return name          # let subprocess fail loudly rather than guessing further


FFMPEG = _tool("ffmpeg")
FFPROBE = _tool("ffprobe")
PEAK_TARGET = 0.95
# ~4 min target; actual cut lands on the nearest pause. NOT arbitrary: DeepFilterNet holds the whole
# file as one tensor, and 8-min chunks blew the CPU allocator ("tried to allocate 395395072 bytes").
# 5 min is known to work on this machine; 4 leaves headroom.
CHUNK_S = 240
SEARCH_S = 30          # how far to hunt for a pause around the target
XFADE_MS = 30

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def decode_headroom(src):
    """Decode to float without clamping, then scale so the true peak fits."""
    cmd = [FFMPEG, "-v", "quiet", "-i", str(src), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    y = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.float32).copy()
    pk = float(np.max(np.abs(y)))
    over = int(np.sum(np.abs(y) > 1.0))
    y *= PEAK_TARGET / pk
    print(f"  decoded {len(y)/SR/60:.1f} min | peak {pk:.4f} ({20*np.log10(pk):+.2f} dBFS), "
          f"{over} samples over full scale -> scaled, none clipped")
    return y


def frame_db(y, frame=4096, block=4096 * 8000):
    """Non-overlapping frame levels in dB, computed in blocks.

    librosa.feature.rms builds the full (frame_length, n_frames) matrix — on a 110-minute file that
    is 4.7 GiB and dies. Non-overlapping frames need no such matrix, and 4096 samples (85 ms) is
    ample resolution for finding pauses and reading a noise floor.
    """
    out = []
    for i in range(0, len(y), block):
        seg = y[i:i + block]
        n = (len(seg) // frame) * frame
        if n == 0:
            break
        b = seg[:n].reshape(-1, frame)
        out.append(np.sqrt(np.mean(b * b, axis=1)))
    if not out:
        return np.array([-120.0])
    return 20 * np.log10(np.maximum(np.concatenate(out), 1e-12))


def silence_cuts(y):
    """Cut points near each CHUNK_S boundary, placed at the quietest frame nearby."""
    hop = 4096
    rdb = frame_db(y, frame=hop)
    fps = SR / hop
    cuts, t = [], CHUNK_S
    total = len(y) / SR
    while t < total - 60:
        lo, hi = int((t - SEARCH_S) * fps), int((t + SEARCH_S) * fps)
        lo, hi = max(0, lo), min(len(rdb) - 1, hi)
        q = lo + int(np.argmin(rdb[lo:hi]))          # quietest frame in the window
        cuts.append(int(q * hop))
        t += CHUNK_S
    return cuts


def run_dfn(src, outdir, atten, tries=3):
    """Run DeepFilterNet, retrying on transient allocator failures.

    DFN holds the whole chunk as one tensor. On a busy machine the allocation can fail even for a
    size that normally fits, so a retry after a pause is worth more than a smaller chunk size.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    # atten=None means FULL strength: omit the flag entirely rather than passing a sentinel.
    cmd = [DFN, "-o", str(outdir), "--no-suffix"]
    if atten is not None:
        cmd += ["--atten-lim", str(atten)]
    cmd += [str(src)]
    last = ""
    for attempt in range(tries):
        r = subprocess.run(cmd, capture_output=True, text=True)
        hits = list(outdir.glob("*.wav"))
        if hits:
            return hits[0]
        last = (r.stderr or "").strip()
        if attempt < tries - 1:
            print(f"      retry {attempt+1}/{tries-1} after allocator failure…")
            gc.collect()
            time.sleep(20)
    raise RuntimeError(f"DeepFilterNet produced nothing after {tries} attempts. "
                       f"Last stderr:\n{last[-1200:]}")


def enhance_chunk(src, dst, atten, work, tag, depth=0):
    """Enhance one chunk, BISECTING AT SILENCE if the CPU allocator refuses.

    DeepFilterNet's peak allocation scales with chunk length, and free RAM on this machine varies
    with whatever else is running (a browser can swing it by a gigabyte). A fixed chunk size is
    therefore always either wasteful or fragile. Halving only the chunks that actually fail adapts
    to whatever memory exists at that moment, and — crucially — keeps every already-processed chunk
    cached instead of forcing a restart.

    Splits land on the quietest frame near the midpoint, so the rejoin is inside a pause.
    """
    tmpdir = work / f"_dfn_{tag}"
    try:
        got = run_dfn(src, tmpdir, atten, tries=2)
        shutil.move(str(got), str(dst))
        shutil.rmtree(tmpdir, ignore_errors=True)
        return
    except RuntimeError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        y, _ = sf.read(str(src), dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        if len(y) / SR < 45 or depth >= 4:
            raise
        mid = len(y) // 2
        win = min(20 * SR, mid - SR)                     # hunt +/-20 s around the middle
        seg = y[mid - win:mid + win]
        rdb = frame_db(seg, frame=2048)
        cut = mid - win + int(np.argmin(rdb)) * 2048     # quietest frame => inside a pause
        print(f"      allocator refused {len(y)/SR/60:.2f} min — splitting at "
              f"{cut/SR/60:.2f} min and retrying both halves")
        parts = []
        for k, (lo, hi) in enumerate([(0, cut), (cut, len(y))]):
            sp = work / f"_split_{tag}_{depth}{k}.wav"
            sf.write(str(sp), y[lo:hi], SR)
            ep = work / f"_split_{tag}_{depth}{k}_enh.wav"
            enhance_chunk(sp, ep, atten, work, f"{tag}_{depth}{k}", depth + 1)
            parts.append(ep)
            sp.unlink(missing_ok=True)
        out = stitch(parts)
        sf.write(str(dst), out.astype("float32"), SR)
        for p in parts:
            p.unlink(missing_ok=True)


def stitch(paths):
    """Concatenate with a short equal-power crossfade; cuts are already in silence."""
    n = int(XFADE_MS * SR / 1000)
    fade_in = np.sqrt(np.linspace(0, 1, n, dtype=np.float32))
    fade_out = np.sqrt(np.linspace(1, 0, n, dtype=np.float32))
    out = None
    for p in paths:
        y, _ = sf.read(str(p), dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        if out is None:
            out = y
            continue
        if len(out) >= n and len(y) >= n:
            out[-n:] = out[-n:] * fade_out + y[:n] * fade_in
            out = np.concatenate([out, y[n:]])
        else:
            out = np.concatenate([out, y])
    return out


def normalise(src_wav, dst_wav, lufs_target):
    """Two-pass EBU R128 loudness normalisation via ffmpeg's loudnorm filter.

    Naive gain does NOT work on this material. Lecture speech has a high crest factor, so lifting the
    integrated loudness to -16 LUFS drives peaks well past full scale; scaling back down to protect
    the peaks then undoes the loudness change. Our first attempt landed at -24.6 LUFS instead of -16
    for exactly this reason.

    loudnorm applies gain AND limits the peaks that would overshoot, so the body of the signal
    actually reaches the target. Two-pass (measure, then apply the measured values) is the accurate
    mode; single-pass is a dynamic estimate and drifts.
    """
    meas = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(src_wav), "-af",
         f"loudnorm=I={lufs_target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", meas, re.S)
    if not m:
        raise RuntimeError(f"loudnorm measurement failed:\n{meas[-800:]}")
    st = json.loads(m.group(0))
    print(f"  measured {float(st['input_i']):.1f} LUFS, true peak {float(st['input_tp']):.1f} dBTP, "
          f"LRA {float(st['input_lra']):.1f}")

    af = (f"loudnorm=I={lufs_target}:TP=-1.5:LRA=11"
          f":measured_I={st['input_i']}:measured_TP={st['input_tp']}"
          f":measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}"
          f":offset={st['target_offset']}:linear=true:print_format=summary")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src_wav),
                    "-af", af, "-ar", str(SR), "-c:a", "pcm_f32le", str(dst_wav)], check=True)

    y, _ = sf.read(str(dst_wav), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    after = pyln.Meter(SR).integrated_loudness(y)
    print(f"  normalised -> {after:.1f} LUFS | peak {20*np.log10(float(np.max(np.abs(y)))):.2f} dBFS")
    return y.astype("float32")


def report(tag, y):
    d = frame_db(y)
    print(f"  {tag:<10} floor {np.percentile(d,5):>7.1f} dB | speech {np.percentile(d,90):>7.1f} dB "
          f"| SNR {np.percentile(d,90)-np.percentile(d,5):>5.1f} dB | zeros {100*np.mean(y==0.0):.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--atten", type=int, default=24)
    ap.add_argument("--lufs", type=float, default=-16.0)
    a = ap.parse_args()

    src = Path(a.src)
    stem = src.stem
    work = OUT / stem / "_work"
    work.mkdir(parents=True, exist_ok=True)
    final_flac = OUT / stem / f"{stem}-enhanced.flac"
    final_mp3 = OUT / stem / f"{stem}-enhanced.mp3"
    t0 = time.time()

    print(f"\n{'='*74}\n{stem}  —  DeepFilterNet3 --atten-lim {a.atten}, target {a.lufs} LUFS\n{'='*74}")

    print("\n[0] DECODE")
    raw = work / "00_raw.wav"
    if raw.exists():
        y, _ = sf.read(str(raw), dtype="float32")
        print(f"  reusing {raw.name} ({len(y)/SR/60:.1f} min)")
    else:
        y = decode_headroom(src)
        sf.write(str(raw), y, SR)
    report("original", y)

    print("\n[1] SPLIT at silence")
    cuts = silence_cuts(y)
    bounds = [0] + cuts + [len(y)]
    print(f"  {len(bounds)-1} chunks, cuts at " +
          ", ".join(f"{c/SR/60:.1f}m" for c in cuts[:6]) + ("…" if len(cuts) > 6 else ""))
    chunks = []
    for i in range(len(bounds) - 1):
        p = work / f"10_chunk{i:02d}.wav"
        if not p.exists():
            sf.write(str(p), y[bounds[i]:bounds[i+1]], SR)
        chunks.append(p)

    # The 110-min float array is ~1.3 GB and is NOT needed again — the chunks are on disk and
    # stitching reads them back. Holding it while DeepFilterNet subprocesses allocate their own
    # tensors is what starved the CPU allocator on the earlier attempts.
    del y
    gc.collect()

    print(f"\n[2] ENHANCE  (DeepFilterNet3, --atten-lim {a.atten})")
    enhanced = []
    for i, c in enumerate(chunks):
        dst = work / f"20_enh{i:02d}.wav"
        if dst.exists():
            print(f"  chunk {i+1}/{len(chunks)}  cached")
        else:
            ts = time.time()
            enhance_chunk(c, dst, a.atten, work, f"{i:02d}")
            dur = sf.info(str(c)).duration
            print(f"  chunk {i+1}/{len(chunks)}  {dur/60:.1f} min in {time.time()-ts:.0f}s "
                  f"(RT {(time.time()-ts)/dur:.3f})")
        enhanced.append(dst)

    print("\n[3] STITCH")
    out = stitch(enhanced)
    print(f"  {len(out)/SR/60:.1f} min, {XFADE_MS} ms crossfades at {len(enhanced)-1} joins")

    print(f"\n[4] NORMALISE to {a.lufs} LUFS")
    stitched = work / "30_stitched.wav"
    sf.write(str(stitched), out, SR)
    del out
    gc.collect()
    tmp = work / "40_final.wav"
    out = normalise(stitched, tmp, a.lufs)
    report("enhanced", out)

    print("\n[5] ENCODE")
    final_flac.parent.mkdir(parents=True, exist_ok=True)
    # 16-bit FLAC. ffmpeg defaults to 24-bit from a float input, which tripled the archive to 570 MB
    # for no gain: the source is a 64 kbps MP3 whose usable dynamic range is nowhere near 96 dB.
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp),
                    "-sample_fmt", "s16", str(final_flac)], check=True)
    # 128k mono is transparent here: the source is 64 kbps band-limited to ~7.7 kHz, so a higher
    # rate only stores encoder noise in empty bands and doubles the download for no audible gain.
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(tmp), "-b:a", "128k",
                    str(final_mp3)], check=True)
    print(f"  {final_flac.name}  {final_flac.stat().st_size/1e6:.1f} MB  (lossless archive)")
    print(f"  {final_mp3.name}  {final_mp3.stat().st_size/1e6:.1f} MB  (distribution)")
    print(f"\ndone in {(time.time()-t0)/60:.1f} min -> {final_flac.parent}")
    print("work files kept in _work/ for resume; delete when satisfied")


if __name__ == "__main__":
    main()
