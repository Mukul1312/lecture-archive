"""
enhance_diagnose.py — Stage 0 for the enhancement pipeline: characterise a recording's DEFECTS
before any tool is chosen.

Implements the diagnostic checklist from docs/enhance-analysis-methodology-research-2026-07-31.md,
in the industry "deepest damage first" order (iZotope RX convention):

  1 INTEGRITY   clipped samples + flat-top runs, DC offset, dropouts   <- deepest; later stages magnify it
  2 LEVEL       peak / RMS / crest factor, speech-vs-silence split
  3 NOISE FLOOR per-block percentiles over time -> STATIONARY or DRIFTING (decides the method class)
  4 NOISE SPEC  mean spectrum of the quietest frames -> hiss vs rumble vs codec junk
  5 TONAL       narrowband peaks above the local median -> is there ACTUALLY hum to notch?
  6 REVERB      blind RT60 from free-decay slopes -> is dereverb even needed?
  7 BANDWIDTH   speech rolloff + energy above the cutoff -> don't denoise empty bands
  8 SNR MARGIN  per-band speech-vs-noise headroom -> sets realistic expectations

The point is NOT to enhance anything. It is to produce the defect inventory that tells you which
candidates are worth testing — and whether "do nothing" is the right answer (a documented outcome:
Hu & Loizou 2007 found most algorithms gave no significant quality benefit).

Local CPU, no models, no GPU, no new dependencies (numpy/scipy/librosa/soundfile only).

RUN:  .venv/Scripts/python.exe scripts/enhance_diagnose.py data/enhance/poc/segment_30min_5min_original.wav
      .venv/Scripts/python.exe scripts/enhance_diagnose.py <wav-or-mp3> [more...] --json out.json
"""
import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import find_peaks

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SR = 48000          # analyse at the source rate; the band-limit is what we're looking for
N_FFT, HOP = 4096, 1024
BANDS = [(0, 60), (60, 120), (120, 180), (180, 320), (320, 1000),
         (1000, 3000), (3000, 6000), (6000, 8000), (8000, 12000), (12000, 24000)]


# ---------------------------------------------------------------- 1. integrity

def integrity(y):
    """Clipping is the deepest defect: true clipping shows as RUNS of samples pinned at full scale.

    A single sample at 0 dBFS is normal; three or more in a row is a flat top, i.e. lost waveform.
    """
    peak = float(np.max(np.abs(y)))
    at_fs = np.abs(y) >= 0.999 * max(peak, 1e-9)
    # length of each consecutive run of pinned samples
    runs, cur = [], 0
    for v in at_fs:
        if v:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    if cur:
        runs.append(cur)
    flat = [r for r in runs if r >= 3]
    return dict(
        peak_dbfs=20 * np.log10(peak + 1e-12),
        pct_at_fullscale=100 * float(np.mean(at_fs)),
        flat_top_runs=len(flat),
        longest_run=int(max(runs)) if runs else 0,
        dc_offset=float(np.mean(y)),
        pct_digital_zero=100 * float(np.mean(y == 0.0)),
    )


# ------------------------------------------------------- 2-3. level + stationarity

def level_and_floor(y, sr):
    """Split frames into speech / silence by an energy threshold, then track the floor over time.

    Stationary floor (small spread across blocks) => classical spectral methods are competitive.
    Drifting floor => you need something adaptive. This single number changes the candidate list.
    """
    rms = librosa.feature.rms(y=y, frame_length=N_FFT, hop_length=HOP)[0]
    rdb = 20 * np.log10(np.maximum(rms, 1e-12))
    floor, speech = np.percentile(rdb, 5), np.percentile(rdb, 90)
    is_speech = rdb > (np.percentile(rdb, 10) + 6.0)

    nblk = 10
    per_block = [float(np.percentile(b, 5)) for b in np.array_split(rdb, nblk) if len(b)]
    drift = max(per_block) - min(per_block)
    return dict(
        rms_dbfs=float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)),
        crest_db=float(20 * np.log10(np.max(np.abs(y)) + 1e-12) - 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-12)),
        speech_pct=100 * float(np.mean(is_speech)),
        floor_db=float(floor),
        speech_db=float(speech),
        snr_db=float(speech - floor),
        floor_per_block=[round(v, 1) for v in per_block],
        floor_drift_db=float(drift),
        stationary=bool(drift < 6.0),
    ), rdb, is_speech


# ------------------------------------------------------------ 4-5. spectrum + hum

def spectra(y, sr, rdb):
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    db = 20 * np.log10(np.maximum(S, 1e-10))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    n = min(len(rdb), db.shape[1])
    quiet = rdb[:n] < np.percentile(rdb, 15)
    loud = rdb[:n] > np.percentile(rdb, 80)
    noise_spec = db[:, :n][:, quiet].mean(axis=1)
    speech_spec = db[:, :n][:, loud].mean(axis=1)
    return freqs, noise_spec, speech_spec


def tonal_peaks(y, sr, rdb_coarse, lo=20, hi=1000, prominence=3.0):
    """Find spectral peaks in the noise floor AND decide whether each is really hum.

    Prominence alone is NOT enough — a speaker's formant is also a prominent peak in "quiet" frames,
    because reverb tails and low-level speech leak into them. Notching a formant carves the voice,
    which is precisely the failure iZotope demonstrates (comb filtering, "heard through a metal tube").

    So each peak gets three discriminating tests:
      width      hum is a pure tone, a few Hz wide; a formant is tens-to-hundreds of Hz
      harmonics  mains hum comes as a series (f, 2f, 3f...); a formant stands alone
      steadiness hum is constant, so it does NOT track the speech envelope; a formant does

    Needs high frequency resolution to measure width at all, hence its own big-FFT analysis.
    """
    n_fft, hop = 16384, 4096
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    db = 20 * np.log10(np.maximum(S, 1e-10))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop)[0]
    rdb = 20 * np.log10(np.maximum(rms, 1e-12))
    n = min(len(rdb), db.shape[1])
    quiet = rdb[:n] < np.percentile(rdb, 15)
    noise_spec = db[:, :n][:, quiet].mean(axis=1)

    m = (freqs >= lo) & (freqs <= hi)
    sub, f = noise_spec[m], freqs[m]
    kernel = 51
    smooth = np.convolve(sub, np.ones(kernel) / kernel, mode="same")
    idx, props = find_peaks(sub - smooth, prominence=prominence)

    def local_excess(hz):
        i = np.argmin(np.abs(freqs - hz))
        return float(noise_spec[i] - np.median(noise_spec[max(0, i - 40):i + 40]))

    out = []
    for k, i_sub in enumerate(idx):
        hz = float(f[i_sub])
        i = np.argmin(np.abs(freqs - hz))

        # -3 dB width
        half = noise_spec[i] - 3.0
        a = i
        while a > 0 and noise_spec[a] > half:
            a -= 1
        b = i
        while b < len(noise_spec) - 1 and noise_spec[b] > half:
            b += 1
        width = float(freqs[b] - freqs[a])

        # harmonic support: how many of 2f..4f (and f/2) also stand above their local median
        harm = sum(1 for mult in (0.5, 2, 3, 4)
                   if hz * mult < freqs[-1] and local_excess(hz * mult) > 3.0)

        # does the band track the speech envelope?
        band = (freqs > hz - 8) & (freqs < hz + 8)
        track = db[band].mean(axis=0)[:n]
        corr = float(np.corrcoef(track, rdb[:n])[0, 1])

        is_hum = (width < 15.0) and (harm >= 2) and (corr < 0.4)
        out.append(dict(hz=round(hz, 1), prominence_db=round(float(props["prominences"][k]), 1),
                        width_hz=round(width, 1), harmonics=harm, speech_corr=round(corr, 2),
                        verdict="HUM" if is_hum else "voice resonance / not hum"))
    return sorted(out, key=lambda d: -d["prominence_db"])[:10]


# ---------------------------------------------------------------- 6. blind RT60

def blind_rt60(y, sr):
    """Estimate RT60 from FREE DECAYS in the energy envelope (speech offsets into room tail).

    Method: find windows where the dB envelope falls monotonically over >=150 ms, fit a line,
    convert slope (dB/s) to the time for a 60 dB drop. Report the median of the fitted decays.

    CAVEAT: this is a pragmatic estimator, not one of the ACE-Challenge benchmarked algorithms.
    Treat it as an order-of-magnitude check ("0.3 s or 2.4 s?"), not a precise measurement.
    """
    hop = 256
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
    rdb = 20 * np.log10(np.maximum(rms, 1e-12))
    t = np.arange(len(rdb)) * hop / sr
    fps = sr / hop
    win = max(int(0.15 * fps), 6)

    slopes = []
    i = 0
    while i < len(rdb) - win:
        seg = rdb[i:i + win]
        # a clean decay: strictly falling overall, starting well above the floor, >=10 dB of fall
        if seg[0] - seg[-1] >= 10 and np.all(np.diff(seg) < 2.0) and seg[0] > np.percentile(rdb, 60):
            a = np.polyfit(t[i:i + win], seg, 1)[0]      # dB per second (negative)
            if a < -5:
                slopes.append(a)
            i += win
        else:
            i += 1

    if not slopes:
        return dict(rt60_s=None, n_decays=0, note="no clean free decays found")
    rt = 60.0 / np.abs(np.array(slopes))
    return dict(
        rt60_s=round(float(np.median(rt)), 2),
        rt60_p25=round(float(np.percentile(rt, 25)), 2),
        rt60_p75=round(float(np.percentile(rt, 75)), 2),
        n_decays=len(slopes),
    )


# ------------------------------------------------------------ 7-8. bandwidth + margin

def bandwidth(freqs, speech_spec):
    lin = 10 ** (speech_spec / 20)
    c = np.cumsum(lin) / np.sum(lin)
    return dict(
        rolloff95_khz=round(float(freqs[np.searchsorted(c, 0.95)]) / 1000, 2),
        rolloff99_khz=round(float(freqs[np.searchsorted(c, 0.99)]) / 1000, 2),
    )


def band_margins(freqs, noise_spec, speech_spec):
    rows = []
    for lo, hi in BANDS:
        m = (freqs >= lo) & (freqs < hi)
        if not m.any():
            continue
        nz, sp = float(noise_spec[m].mean()), float(speech_spec[m].mean())
        rows.append(dict(lo=lo, hi=hi, noise_db=round(nz, 1), speech_db=round(sp, 1),
                         margin_db=round(sp - nz, 1)))
    return rows


# ---------------------------------------------------------------------- report

def diagnose(path):
    y, sr = librosa.load(str(path), sr=SR, mono=True)
    integ = integrity(y)
    lvl, rdb, _ = level_and_floor(y, sr)
    freqs, noise_spec, speech_spec = spectra(y, sr, rdb)
    return dict(
        file=str(path), dur_s=round(len(y) / sr, 1),
        integrity=integ, level=lvl,
        tonal=tonal_peaks(y, sr, rdb),
        reverb=blind_rt60(y, sr),
        bandwidth=bandwidth(freqs, speech_spec),
        bands=band_margins(freqs, noise_spec, speech_spec),
    )


def verdicts(d):
    """Turn measurements into the decisions they imply. This is the actual deliverable."""
    v, i, l, t, r, b = [], d["integrity"], d["level"], d["tonal"], d["reverb"], d["bandwidth"]

    if i["flat_top_runs"] > 0:
        v.append(f"CLIPPING: {i['flat_top_runs']} flat-top runs (longest {i['longest_run']} samples) "
                 f"-> declip FIRST; it is the deepest defect and later stages magnify it")
    else:
        v.append("CLIPPING: none detected -> no declip stage needed")

    if abs(i["dc_offset"]) > 1e-3:
        v.append(f"DC OFFSET: {i['dc_offset']:+.4f} -> high-pass to remove before anything else")

    v.append(f"NOISE FLOOR: {'STATIONARY' if l['stationary'] else 'DRIFTING'} "
             f"({l['floor_drift_db']:.1f} dB spread across the file) -> "
             + ("gentle classical spectral methods are competitive; adaptive profiling is unnecessary"
                if l["stationary"] else "needs an adaptive/neural method that tracks the floor"))

    hums = [p for p in t if p["verdict"] == "HUM"]
    if hums:
        v.append("TONAL: real hum at " + ", ".join(f"{p['hz']} Hz" for p in hums)
                 + " -> notch ONLY these frequencies")
    elif t:
        v.append(f"TONAL: {len(t)} prominent peak(s) found but NONE are hum (too wide, no harmonic "
                 f"series, and they track the speech envelope) -> these are the speaker's formants. "
                 f"DO NOT notch — that would carve his voice and cause comb filtering")
    else:
        v.append("TONAL: no narrowband peaks at all -> no notch stage needed")

    if r["rt60_s"] is None:
        v.append("REVERB: could not estimate (no clean free decays) -> inspect manually")
    elif r["rt60_s"] < 0.5:
        v.append(f"REVERB: RT60 ~{r['rt60_s']} s (dry) -> dereverberation is NOT a reason to pick a "
                 f"heavyweight joint model")
    elif r["rt60_s"] < 1.0:
        v.append(f"REVERB: RT60 ~{r['rt60_s']} s (moderate) -> mild dereverb may help; keep some room sound")
    else:
        v.append(f"REVERB: RT60 ~{r['rt60_s']} s (live) -> dereverb genuinely matters; joint model justified")

    v.append(f"BANDWIDTH: speech ends at {b['rolloff95_khz']} kHz (95%) -> treat everything above "
             f"{b['rolloff99_khz']} kHz as empty; do not let a denoiser invent content there")

    v.append(f"SNR: {l['snr_db']:.1f} dB speech-over-floor. "
             + ("Already high — the honest question is whether ANY processing improves the listening "
                "experience (Hu & Loizou: often it does not)" if l["snr_db"] > 25
                else "Real headroom to gain from denoising"))
    return v


def show(d):
    i, l, b = d["integrity"], d["level"], d["bandwidth"]
    print(f"\n{'='*78}\n{Path(d['file']).name}   {d['dur_s']}s\n{'='*78}")

    print("\n[1] INTEGRITY")
    print(f"    peak {i['peak_dbfs']:.1f} dBFS | at full-scale {i['pct_at_fullscale']:.3f}% | "
          f"flat-top runs {i['flat_top_runs']} (longest {i['longest_run']})")
    print(f"    DC offset {i['dc_offset']:+.5f} | digital-zero samples {i['pct_digital_zero']:.2f}%")

    print("\n[2] LEVEL")
    print(f"    RMS {l['rms_dbfs']:.1f} dBFS | crest {l['crest_db']:.1f} dB | speech frames {l['speech_pct']:.0f}%")

    print("\n[3] NOISE FLOOR OVER TIME")
    print(f"    per-block p05: {'  '.join(f'{v:.0f}' for v in l['floor_per_block'])}  dB")
    print(f"    drift {l['floor_drift_db']:.1f} dB -> {'STATIONARY' if l['stationary'] else 'DRIFTING'}"
          f" | speech {l['speech_db']:.1f} dB | SNR {l['snr_db']:.1f} dB")

    print("\n[4] TONAL PEAKS IN NOISE FLOOR (hum check, 20-1000 Hz; hum = narrow + harmonic + not speech-tracking)")
    if d["tonal"]:
        print(f"    {'Hz':>9}{'promin':>9}{'-3dB width':>12}{'harmonics':>11}{'speech corr':>13}   verdict")
        for p in d["tonal"]:
            print(f"    {p['hz']:>9.1f}{p['prominence_db']:>8.1f}dB{p['width_hz']:>11.1f}Hz"
                  f"{p['harmonics']:>11}{p['speech_corr']:>13.2f}   {p['verdict']}")
    else:
        print("    none — no narrowband peaks present")

    r = d["reverb"]
    print("\n[5] BLIND RT60 (free-decay slope fit; order-of-magnitude only)")
    print(f"    {r['rt60_s']} s (p25 {r.get('rt60_p25')} / p75 {r.get('rt60_p75')}), "
          f"from {r['n_decays']} decays" if r["rt60_s"] else f"    {r['note']}")

    print("\n[6] BANDWIDTH")
    print(f"    speech rolloff  95% {b['rolloff95_khz']} kHz | 99% {b['rolloff99_khz']} kHz")

    print("\n[7] PER-BAND SNR MARGIN")
    print(f"    {'band':<16}{'noise':>9}{'speech':>9}{'margin':>9}")
    for row in d["bands"]:
        band = "{}-{} Hz".format(row["lo"], row["hi"])
        print(f"    {band:<16}{row['noise_db']:>9.1f}{row['speech_db']:>9.1f}{row['margin_db']:>9.1f}")

    print("\n[8] VERDICTS -> what this implies for treatment")
    for line in verdicts(d):
        print(f"    * {line}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", default=None, help="write full results to this path")
    a = ap.parse_args()

    results = []
    for f in a.files:
        d = diagnose(f)
        show(d)
        results.append(d)

    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
