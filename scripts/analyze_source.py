"""
analyze_source.py — HINDI Stage 0: cheap acoustic-quality triage of the raw source lectures.

Answers "how usable is this material?" BEFORE the expensive transcription labor. Local CPU, no models,
no GPU. Per lecture it reports: duration, energy-VAD speech ratio, loudness (median speech RMS dBFS),
peak + % clipped samples, a rough noise floor and SNR (p90-p10 of frame energy), and effective bandwidth
(median 95% spectral rolloff over speech frames — exposes the low-bitrate band-limit: these files are
56 kbps MP3, so expect the rolloff well below 8 kHz).

This is only the ACOUSTIC half. The CONTENT half — speaker diarization (GGS-vs-questioner share) and
ASR language-ID (how much is actually Hindi vs Odia/Sanskrit/English/chanting) — needs models on a pod;
see research/docs/hindi/hindi-clone-plan.md. Run this first: it is free and it sizes the trainable pool.

RUN:  python scripts/analyze_source.py                    # all data/hi/lectures/*/audio.mp3
      python scripts/analyze_source.py path/to/audio.mp3 ...
"""
import glob
import os
import sys

import librosa
import numpy as np

SR = 16000          # VoxCPM works at 16 kHz internally; analyze at the rate that matters
FRAME, HOP = 2048, 512


def analyze(path: str) -> dict:
    y, _ = librosa.load(path, sr=SR, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP)[0]
    rms_db = 20 * np.log10(np.maximum(rms, 1e-9))
    noise_db = float(np.percentile(rms_db, 10))          # quietest frames ~ noise floor
    loud_db = float(np.percentile(rms_db, 90))           # loudest frames ~ speech peaks
    speech = rms_db > (noise_db + 6.0)                    # 6 dB over floor = "speech"
    S = np.abs(librosa.stft(y, n_fft=FRAME, hop_length=HOP))
    roll = librosa.feature.spectral_rolloff(S=S, sr=SR, roll_percent=0.95)[0]
    n = min(len(roll), len(speech))
    bw = float(np.median(roll[:n][speech[:n]])) if speech[:n].any() else float(np.median(roll))
    return dict(
        dur=len(y) / SR,
        speech_ratio=100 * float(np.mean(speech)),
        speech_rms=float(np.median(rms_db[speech])) if speech.any() else loud_db,
        peak_db=float(20 * np.log10(max(float(np.max(np.abs(y))), 1e-9))),
        clip_pct=100 * float(np.mean(np.abs(y) > 0.99)),
        noise_db=noise_db,
        snr=loud_db - noise_db,
        bw_khz=bw / 1000,
    )


def main():
    files = sys.argv[1:] or sorted(glob.glob("data/hi/lectures/*/audio.mp3"))
    if not files:
        sys.exit("no files — run scripts/fetch_idt.py first")
    print(f"{'lecture':<24}{'min':>6}{'speech%':>8}{'RMS dB':>8}{'peak dB':>8}"
          f"{'clip%':>7}{'noise dB':>9}{'SNR dB':>7}{'BW kHz':>7}")
    tot = 0.0
    for f in files:
        name = os.path.basename(os.path.dirname(f)) or os.path.basename(f)
        a = analyze(f)
        tot += a["dur"]
        print(f"{name:<24}{a['dur']/60:>6.1f}{a['speech_ratio']:>8.0f}{a['speech_rms']:>8.1f}"
              f"{a['peak_db']:>8.1f}{a['clip_pct']:>7.2f}{a['noise_db']:>9.1f}{a['snr']:>7.1f}"
              f"{a['bw_khz']:>7.1f}")
    print(f"{'TOTAL':<24}{tot/60:>6.1f}  ({tot/3600:.2f} h)")
    print("\nreads: BW kHz << 8 confirms the 56 kbps band-limit; high noise dB / low SNR = noisy source; "
          "speech% under ~100 = silence/pauses (or Q&A gaps). Content mix (Hindi vs Odia/Sanskrit, GGS vs "
          "questioner) needs the pod diarization + ASR pass.")


if __name__ == "__main__":
    main()
