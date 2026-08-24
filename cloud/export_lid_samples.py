"""
export_lid_samples.py — cut ear-check sample clips per MMS-LID language, from the SAVED windows.

Reads data/hi/lectures/*/content_triage_mms.json (produced by odia_check.py) and, for each target
language, exports the N highest-confidence windows as wavs into data/hi/lid_samples/<lang>/ — so you
can listen and judge: is this REALLY that language, or his accented Hindi mislabelled? No MMS re-run.
  python cloud/export_lid_samples.py --langs hin,npi,ben,eng,ory,guj,asm --n 8
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HI = ROOT / "data" / "hi" / "lectures"


def to_wav_16k(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-ac", "1", "-ar", "16000", str(dst)], check=True)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="hin,npi,ben,eng,ory,guj,asm")
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    langs = [x.strip() for x in a.langs.split(",") if x.strip()]
    out = ROOT / "data" / "hi" / "lid_samples"
    bylang = {l: [] for l in langs}
    for d in sorted(HI.iterdir()):
        mj = d / "content_triage_mms.json"
        if not mj.exists():
            continue
        wav = to_wav_16k(d / "audio.mp3", ROOT / "_work" / f"hi_{d.name}.wav")
        for w in json.loads(mj.read_text(encoding="utf-8")).get("mms_windows", []):
            if w["lang"] in bylang:
                bylang[w["lang"]].append((w["prob"], d.name, w["start"], w["end"], str(wav)))

    for l in langs:
        ws = sorted(bylang[l], key=lambda x: -x[0])[:a.n]
        od = out / l
        od.mkdir(parents=True, exist_ok=True)
        for f in od.glob("*.wav"):
            f.unlink()
        for i, (p, slug, s, e, wav) in enumerate(ws, 1):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-ss", str(s), "-to", str(e),
                            str(od / f"{l}_{i:02d}_{slug[-2:]}_{int(s)}s_p{int(p*100)}.wav")])
        print(f"  {l}: {len(bylang[l])} windows total, exported top {len(ws)} -> {od}")
    print(f"done -> {out}")


if __name__ == "__main__":
    main()
