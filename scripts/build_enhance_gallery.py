"""
build_enhance_gallery.py — A/B comparison gallery for enhancement proof-of-concept

Shows before/after enhancement clips side-by-side with:
- Audio players (RMS-matched for fair comparison)
- Spectrograms (0-8 kHz)
- Measured metrics (SNR, noise floor, etc.)

Output: voice_lab/enhance_poc/
Run: .venv/Scripts/python.exe scripts/build_enhance_gallery.py
"""
import json
import shutil
import sys
from pathlib import Path

import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "data/enhance/poc/segment_30min_5min.wav"
AFTER = ROOT / "data/enhance/poc/segment_30min_5min_DeepFilterNet3_pf.wav"
OUT = ROOT / "voice_lab" / "enhance_poc"
AUD = OUT / "audio"
IMG = OUT / "img"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TARGET_RMS = 0.06  # Normalize both to same RMS for fair comparison


def rms_match(src, dst):
    """Normalize to common RMS so loudness doesn't bias perception."""
    y, sr = sf.read(str(src), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    r = float(np.sqrt(np.mean(y * y))) + 1e-9
    y = y * (TARGET_RMS / r)
    pk = float(np.max(np.abs(y)))
    if pk > 0.99:
        y = y * (0.99 / pk)
    sf.write(str(dst), y.astype("float32"), sr)


def spec_png(wav_path, out_png):
    """0-8 kHz dB spectrogram for visualization."""
    if out_png.exists():
        return
    y, sr = librosa.load(str(wav_path), sr=16000)
    S = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=1024, hop_length=256)), ref=np.max)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    keep = freqs <= 8000
    fig, ax = plt.subplots(figsize=(8, 2.5), dpi=100)
    ax.imshow(S[keep], origin="lower", aspect="auto", cmap="magma",
              extent=[0, len(y) / sr, 0, 8], vmin=-80, vmax=0)
    ax.set_xlabel("Time (s)", fontsize=10)
    ax.set_ylabel("Freq (kHz)", fontsize=10)
    ax.set_title(out_png.stem.replace("_", " ").title(), fontsize=11)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight", dpi=100)
    plt.close(fig)


def analyze(path):
    """Compute acoustic metrics."""
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


def build_html():
    """Generate comparison gallery HTML."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enhancement Proof-of-Concept</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: #f8f9fa;
  padding: 20px;
  line-height: 1.6;
}
.container { max-width: 1200px; margin: 0 auto; }
h1 {
  color: #1a1a1a;
  margin-bottom: 10px;
  font-size: 28px;
}
.subtitle {
  color: #666;
  margin-bottom: 30px;
  font-size: 14px;
}
.info-box {
  background: #e7f3ff;
  border-left: 4px solid #0066cc;
  padding: 15px;
  margin-bottom: 25px;
  border-radius: 4px;
}
.comparison {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 25px;
  margin-bottom: 30px;
}
.panel {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
}
.panel h2 {
  font-size: 18px;
  margin-bottom: 15px;
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
.badge.before { background: #ffe0e0; color: #cc0000; }
.badge.after { background: #d4f4dd; color: #00802b; }
audio {
  width: 100%;
  margin: 15px 0;
}
.spectrogram {
  width: 100%;
  height: auto;
  border-radius: 4px;
  margin: 15px 0;
  border: 1px solid #e0e0e0;
}
.metrics {
  background: #f8f9fa;
  padding: 15px;
  border-radius: 4px;
  font-size: 13px;
}
.metrics dl { display: grid; grid-template-columns: auto 1fr; gap: 8px 15px; }
.metrics dt { font-weight: 600; color: #555; }
.metrics dd { color: #333; text-align: right; }
.processing-info {
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-top: 25px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.08);
}
.processing-info h3 {
  font-size: 16px;
  margin-bottom: 12px;
  color: #333;
}
.processing-info table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.processing-info th {
  background: #f8f9fa;
  padding: 10px;
  text-align: left;
  font-weight: 600;
  border-bottom: 2px solid #dee2e6;
}
.processing-info td {
  padding: 10px;
  border-bottom: 1px solid #e9ecef;
}
.delta-positive {
  color: #00802b;
  font-weight: 600;
}
@media (max-width: 768px) {
  .comparison { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
  <h1>🎧 DeepFilterNet3 Enhancement Proof-of-Concept</h1>
  <div class="subtitle">Jiva Goswami Seminar Part-01 • 5-minute segment (30:00-35:00)</div>

  <div class="info-box">
    <strong>Processing:</strong> DeepFilterNet3 (epoch 120) with post-filter (beta 0.02, conservative)<br>
    <strong>Time:</strong> 30 seconds to process 5 minutes (RT factor: 0.100 = 10× real-time)<br>
    <strong>Note:</strong> Both clips RMS-matched to 0.06 for fair loudness comparison
  </div>

  <div class="comparison">
    <div class="panel">
      <h2><span class="badge before">Before</span> Original</h2>
      <audio controls preload="metadata">
        <source src="audio/before.wav" type="audio/wav">
      </audio>
      <img src="img/before_spectrogram.png" alt="Before spectrogram" class="spectrogram">
      <div class="metrics">
        <dl>
          <dt>RMS Level:</dt><dd>{{before_rms}} dB</dd>
          <dt>Peak Level:</dt><dd>{{before_peak}} dB</dd>
          <dt>Noise Floor:</dt><dd>{{before_noise}} dB</dd>
          <dt>SNR:</dt><dd>{{before_snr}} dB</dd>
        </dl>
      </div>
    </div>

    <div class="panel">
      <h2><span class="badge after">After</span> Enhanced</h2>
      <audio controls preload="metadata">
        <source src="audio/after.wav" type="audio/wav">
      </audio>
      <img src="img/after_spectrogram.png" alt="After spectrogram" class="spectrogram">
      <div class="metrics">
        <dl>
          <dt>RMS Level:</dt><dd>{{after_rms}} dB</dd>
          <dt>Peak Level:</dt><dd>{{after_peak}} dB</dd>
          <dt>Noise Floor:</dt><dd>{{after_noise}} dB</dd>
          <dt>SNR:</dt><dd>{{after_snr}} dB</dd>
        </dl>
      </div>
    </div>
  </div>

  <div class="processing-info">
    <h3>📊 Measured Improvements</h3>
    <table>
      <tr>
        <th>Metric</th>
        <th>Before</th>
        <th>After</th>
        <th>Change</th>
      </tr>
      <tr>
        <td>Noise Floor</td>
        <td>{{before_noise}} dB</td>
        <td>{{after_noise}} dB</td>
        <td class="delta-positive">{{noise_delta}} dB</td>
      </tr>
      <tr>
        <td>SNR (Signal-to-Noise)</td>
        <td>{{before_snr}} dB</td>
        <td>{{after_snr}} dB</td>
        <td class="delta-positive">{{snr_delta}} dB</td>
      </tr>
    </table>

    <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #dee2e6; font-size: 13px; color: #666;">
      <strong>What to listen for:</strong><br>
      • Background hiss/room tone (should be much quieter)<br>
      • Echo/reverb reduction (partial, not eliminated)<br>
      • Voice naturalness (should sound like him, just in a quieter room)<br>
      • No processing artifacts (underwater/metallic quality)<br>
      • Soft speech preservation (quiet words should remain clear)
    </div>
  </div>
</div>
</body>
</html>"""
    return html


def main():
    print("Building enhancement comparison gallery...")

    # Setup directories
    OUT.mkdir(parents=True, exist_ok=True)
    AUD.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)

    # RMS-match audio files
    print("  Normalizing audio for fair comparison...")
    rms_match(BEFORE, AUD / "before.wav")
    rms_match(AFTER, AUD / "after.wav")

    # Generate spectrograms
    print("  Generating spectrograms...")
    spec_png(AUD / "before.wav", IMG / "before_spectrogram.png")
    spec_png(AUD / "after.wav", IMG / "after_spectrogram.png")

    # Analyze metrics
    print("  Computing metrics...")
    before_metrics = analyze(BEFORE)
    after_metrics = analyze(AFTER)

    # Calculate deltas
    noise_delta = after_metrics["noise_db"] - before_metrics["noise_db"]
    snr_delta = after_metrics["snr_db"] - before_metrics["snr_db"]

    # Build HTML
    print("  Generating HTML...")
    html = build_html()
    html = html.replace("{{before_rms}}", str(before_metrics["rms_db"]))
    html = html.replace("{{before_peak}}", str(before_metrics["peak_db"]))
    html = html.replace("{{before_noise}}", str(before_metrics["noise_db"]))
    html = html.replace("{{before_snr}}", str(before_metrics["snr_db"]))
    html = html.replace("{{after_rms}}", str(after_metrics["rms_db"]))
    html = html.replace("{{after_peak}}", str(after_metrics["peak_db"]))
    html = html.replace("{{after_noise}}", str(after_metrics["noise_db"]))
    html = html.replace("{{after_snr}}", str(after_metrics["snr_db"]))
    html = html.replace("{{noise_delta}}", f"{noise_delta:+.1f}")
    html = html.replace("{{snr_delta}}", f"{snr_delta:+.1f}")

    (OUT / "index.html").write_text(html, encoding="utf-8")

    # Save metrics to JSON
    metrics_data = {
        "before": before_metrics,
        "after": after_metrics,
        "deltas": {
            "noise_floor_db": round(noise_delta, 1),
            "snr_db": round(snr_delta, 1),
        },
        "processing": {
            "model": "DeepFilterNet3",
            "epoch": 120,
            "post_filter_beta": 0.02,
            "rt_factor": 0.100,
            "processing_time_seconds": 30,
            "audio_duration_seconds": 300,
        }
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")

    print(f"\n✓ Gallery built: {OUT}/")
    print(f"  Open: {OUT}/index.html")
    print(f"\n  Before: SNR {before_metrics['snr_db']} dB, Noise floor {before_metrics['noise_db']} dB")
    print(f"  After:  SNR {after_metrics['snr_db']} dB, Noise floor {after_metrics['noise_db']} dB")
    print(f"  Delta:  SNR {snr_delta:+.1f} dB, Noise floor {noise_delta:+.1f} dB")


if __name__ == "__main__":
    main()
