"""trim_leadin.py — remove the 'हे जी।' carrier: cut everything up to the end of the first silence gap
(the danda pause after the lead-in). Robust energy-based. Writes *_trim.wav next to each input."""
import sys, glob
from pathlib import Path
import numpy as np, soundfile as sf

def trim_leadin(y, sr, drop_db=35.0, min_lead=0.12, gap=0.14):
    win = int(0.025 * sr); hop = int(0.01 * sr)
    if len(y) < win * 4:
        return y
    db = np.array([20 * np.log10(np.sqrt(np.mean(y[i:i+win] ** 2)) + 1e-9)
                   for i in range(0, len(y) - win, hop)])
    sil = db < (db.max() - drop_db)
    gf, lf = int(gap / 0.01), int(min_lead / 0.01)
    i = lf
    while i < len(sil) - gf:
        if sil[i:i + gf].all():                       # first real pause after the lead-in
            j = i + gf
            while j < len(sil) and sil[j]:
                j += 1
            return y[j * hop:]
        i += 1
    return y                                           # no clear gap -> leave as-is

if __name__ == "__main__":
    for p in sorted(glob.glob(sys.argv[1])):
        y, sr = sf.read(p, dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        t = trim_leadin(y, sr)
        out = str(Path(p).with_name(Path(p).stem + "_trim.wav"))
        sf.write(out, t, sr)
        print(f"{Path(p).name}: {len(y)/sr:.2f}s -> {len(t)/sr:.2f}s  (cut {(len(y)-len(t))/sr:.2f}s)")
