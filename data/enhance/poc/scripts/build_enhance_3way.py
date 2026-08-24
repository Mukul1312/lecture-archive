"""
build_enhance_3way.py — 3-way enhancement comparison: Original vs DFN (no PF) vs DFN (with PF)

Output: voice_lab/enhance_3way/
Run: .venv/Scripts/python.exe scripts/build_enhance_3way.py
"""
import json
import sys
from pathlib import Path

import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
POC = ROOT / "data/enhance/poc"
ORIGINAL = POC / "segment_30min_5min_original.wav"
NO_PF = POC / "segment_30min_5min_no_pf.wav"
WITH_PF = POC / "segment_30min_5min_with_pf.wav"
OUT = ROOT / "voice_lab" / "enhance_3way"
AUD = OUT / "audio"
IMG = OUT / "img"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TARGET_RMS = 0.06


def rms_match(src, dst):
    y, sr = sf.read(str(src), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    r = float(np.sqrt(np.mean(y * y))) + 1e-9
    y = y * (TARGET_RMS / r)
    pk = float(np.max(np.abs(y)))
    if pk > 0.99:
        y = y * (0.99 / pk)
    sf.write(str(dst), y.astype("float32"), sr)


def spec_png(wav_path, out_png, title):
    if out_png.exists():
        return
    y, sr = librosa.load(str(wav_path), sr=16000)
    S = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=1024, hop_length=256)), ref=np.max)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    keep = freqs <= 8000
    fig, ax = plt.subplots(figsize=(7, 2), dpi=100)
    ax.imshow(S[keep], origin="lower", aspect="auto", cmap="magma",
              extent=[0, len(y) / sr, 0, 8], vmin=-80, vmax=0)
    ax.set_xlabel("Time (s)", fontsize=9)
    ax.set_ylabel("kHz", fontsize=9)
    ax.set_title(title, fontsize=10, pad=8)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight", dpi=100)
    plt.close(fig)


def analyze(path):
    y, sr = librosa.load(str(path), sr=48000, mono=True)
    rms = 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-10)
    peak = 20 * np.log10(np.max(np.abs(y)) + 1e-10)
    sorted_energy = np.sort(y ** 2)
    noise_floor = np.sqrt(np.mean(sorted_energy[:int(len(sorted_energy) * 0.05)]))
    noise_db = 20 * np.log10(noise_floor + 1e-10)
    snr = rms - noise_db
    return {
        "rms_db": round(rms, 1),
        "peak_db": round(peak, 1),
        "noise_db": round(noise_db, 1),
        "snr_db": round(snr, 1),
    }


def build_html(orig_m, no_pf_m, with_pf_m):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>3-Way Enhancement Comparison</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: #f8f9fa;
  padding: 20px;
  line-height: 1.6;
}
.container { max-width: 1400px; margin: 0 auto; }
h1 { color: #1a1a1a; margin-bottom: 10px; font-size: 28px; }
.subtitle { color: #666; margin-bottom: 25px; font-size: 14px; }
.info-box {
  background: #fff3cd;
  border-left: 4px solid #ffc107;
  padding: 15px;
  margin-bottom: 25px;
  border-radius: 4px;
  font-size: 14px;
}
.comparison {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-bottom: 30px;
}
.panel {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
}
.panel h2 {
  font-size: 16px;
  margin-bottom: 12px;
  color: #333;
  display: flex;
  align-items: center;
  gap: 8px;
}
.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.badge.original { background: #e0e0e0; color: #424242; }
.badge.light { background: #e3f2fd; color: #1565c0; }
.badge.aggressive { background: #fce4ec; color: #c2185b; }
audio { width: 100%; margin: 12px 0; }
.spectrogram {
  width: 100%;
  height: auto;
  border-radius: 4px;
  margin: 12px 0;
  border: 1px solid #e0e0e0;
}
.metrics {
  background: #f8f9fa;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
}
.metrics dl { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; }
.metrics dt { font-weight: 600; color: #555; }
.metrics dd { color: #333; text-align: right; }
.note {
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-top: 25px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
}
.note h3 { font-size: 16px; margin-bottom: 12px; color: #333; }
.note ul { margin-left: 20px; font-size: 14px; line-height: 1.8; }
@media (max-width: 1024px) {
  .comparison { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
  <h1>🎧 3-Way Enhancement Comparison</h1>
  <div class="subtitle">Jiva Goswami Seminar Part-01 • 5-minute segment (30:00-35:00)</div>

  <div class="info-box">
    <strong>⚠️ Voice naturalness test:</strong> User feedback indicates the enhanced version "feels not natural" — testing different DeepFilterNet settings to find the right balance between noise reduction and voice character preservation.
  </div>

  <div class="comparison">
    <div class="panel">
      <h2><span class="badge original">Original</span></h2>
      <audio controls preload="metadata">
        <source src="audio/original.wav" type="audio/wav">
      </audio>
      <img src="img/original.png" alt="Original" class="spectrogram">
      <div class="metrics">
        <dl>
          <dt>SNR:</dt><dd>{{orig_snr}} dB</dd>
          <dt>Noise:</dt><dd>{{orig_noise}} dB</dd>
          <dt>RMS:</dt><dd>{{orig_rms}} dB</dd>
        </dl>
      </div>
      <p style="margin-top:10px; font-size:13px; color:#666;">
        Untouched source — full noise but natural voice character
      </p>
    </div>

    <div class="panel">
      <h2><span class="badge light">DFN (Light)</span></h2>
      <audio controls preload="metadata">
        <source src="audio/no_pf.wav" type="audio/wav">
      </audio>
      <img src="img/no_pf.png" alt="No post-filter" class="spectrogram">
      <div class="metrics">
        <dl>
          <dt>SNR:</dt><dd>{{no_pf_snr}} dB</dd>
          <dt>Noise:</dt><dd>{{no_pf_noise}} dB</dd>
          <dt>RMS:</dt><dd>{{no_pf_rms}} dB</dd>
        </dl>
      </div>
      <p style="margin-top:10px; font-size:13px; color:#666;">
        DeepFilterNet3 base model (no post-filter) — conservative processing
      </p>
    </div>

    <div class="panel">
      <h2><span class="badge aggressive">DFN (Aggressive)</span></h2>
      <audio controls preload="metadata">
        <source src="audio/with_pf.wav" type="audio/wav">
      </audio>
      <img src="img/with_pf.png" alt="With post-filter" class="spectrogram">
      <div class="metrics">
        <dl>
          <dt>SNR:</dt><dd>{{with_pf_snr}} dB</dd>
          <dt>Noise:</dt><dd>{{with_pf_noise}} dB</dd>
          <dt>RMS:</dt><dd>{{with_pf_rms}} dB</dd>
        </dl>
      </div>
      <p style="margin-top:10px; font-size:13px; color:#666;">
        DeepFilterNet3 + post-filter (beta 0.02) — strongest noise suppression
      </p>
    </div>
  </div>

  <div class="note">
    <h3>🎯 Which sounds most natural?</h3>
    <p style="margin-bottom:12px; font-size:14px;">Listen for:</p>
    <ul>
      <li><strong>Voice character preservation:</strong> Does it still sound like him?</li>
      <li><strong>Natural timbre:</strong> No "underwater" or "metallic" quality</li>
      <li><strong>Breath/soft sounds:</strong> Natural speaking dynamics preserved</li>
      <li><strong>Noise reduction:</strong> Cleaner background without voice artifacts</li>
    </ul>
    <p style="margin-top:15px; padding-top:15px; border-top:1px solid #dee2e6; font-size:13px; color:#666;">
      If <strong>all three</strong> sound unnatural compared to the original, we'll try a different tool (noisereduce with spectral gating, or even skipping enhancement for this corpus).
    </p>
  </div>
</div>
</body>
</html>"""

    html = html.replace("{{orig_snr}}", str(orig_m["snr_db"]))
    html = html.replace("{{orig_noise}}", str(orig_m["noise_db"]))
    html = html.replace("{{orig_rms}}", str(orig_m["rms_db"]))
    html = html.replace("{{no_pf_snr}}", str(no_pf_m["snr_db"]))
    html = html.replace("{{no_pf_noise}}", str(no_pf_m["noise_db"]))
    html = html.replace("{{no_pf_rms}}", str(no_pf_m["rms_db"]))
    html = html.replace("{{with_pf_snr}}", str(with_pf_m["snr_db"]))
    html = html.replace("{{with_pf_noise}}", str(with_pf_m["noise_db"]))
    html = html.replace("{{with_pf_rms}}", str(with_pf_m["rms_db"]))

    return html


def main():
    print("Building 3-way enhancement comparison...")

    OUT.mkdir(parents=True, exist_ok=True)
    AUD.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)

    print("  Normalizing audio...")
    rms_match(ORIGINAL, AUD / "original.wav")
    rms_match(NO_PF, AUD / "no_pf.wav")
    rms_match(WITH_PF, AUD / "with_pf.wav")

    print("  Generating spectrograms...")
    spec_png(AUD / "original.wav", IMG / "original.png", "Original (untouched)")
    spec_png(AUD / "no_pf.wav", IMG / "no_pf.png", "DeepFilterNet3 (no post-filter)")
    spec_png(AUD / "with_pf.wav", IMG / "with_pf.png", "DeepFilterNet3 (with post-filter)")

    print("  Computing metrics...")
    orig_m = analyze(ORIGINAL)
    no_pf_m = analyze(NO_PF)
    with_pf_m = analyze(WITH_PF)

    print("  Generating HTML...")
    html = build_html(orig_m, no_pf_m, with_pf_m)
    (OUT / "index.html").write_text(html, encoding="utf-8")

    metrics_data = {
        "original": orig_m,
        "no_post_filter": no_pf_m,
        "with_post_filter": with_pf_m,
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")

    print(f"\n✓ 3-way gallery built: {OUT}/")
    print(f"  Open: {OUT}/index.html")
    print(f"\n  Original:    SNR {orig_m['snr_db']} dB")
    print(f"  No PF:       SNR {no_pf_m['snr_db']} dB")
    print(f"  With PF:     SNR {with_pf_m['snr_db']} dB")


if __name__ == "__main__":
    main()
