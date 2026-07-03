"""
prep_narration.py — turn the diary devotional text (PART A framing + PART B his first-person diary)
into VoxCPM-ready utterances: transliterate IAST->ASCII (our locked pronunciation step) and split into
natural sentence-length chunks (each well under the ~20s autoregressive ceiling, cut at sentence ends
so prosody flows). Writes data/narration/diary_chunks.txt (one utterance per line) for cloud/narrate.py.
Run: .venv/Scripts/python.exe scripts/prep_narration.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from classify_transliterate import transliterate   # Kṛṣṇa -> Krishna (locked lossy IAST->ASCII map)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# spoken-form chunks (IAST diacritics preserved here; transliterate() fixes them). Dates spelled out,
# (1)(2)(3) -> first/second/third, brackets removed — so the TTS reads them naturally.
CHUNKS = [
    # --- PART A: narration / framing (third-person intro) ---
    "On the 8th of May, 1975, Maharaj once again recorded in his own hand-written diary the reasons for giving up night Prasādam.",
    "Mahārāja also expressed repentance and prayed for forgiveness at the lotus feet of the Lord, for having accepted some Prasādam under certain exceptional circumstances.",
    "In particular, Mahārāja mentioned three specific reasons for giving up night Prasādam, which are presented as follows.",
    # --- PART B: the diary entry (his own first-person words) ---
    "8th May, 1975. Thursday. This servant took a vow not to eat anything at night, except a little mahā-water with Tulasī.",
    "This vow is meant: first, to open an ISKCON centre in Odisha.",
    "Second, to utilise the servant's dearmost Gopāla's place as one of the branches of ISKCON.",
    "And third, for receiving complete and uninterrupted kṛṣṇa-prema.",
    "Unless this servant achieves success in these three things, he will not accept any Prasādam at night.",
    "Oh Lord! This servant has already taken a vow for that.",
    "But what an astonishing līlā You are performing; may Your auspicious desire be fulfilled.",
    "But oh Lord! Today this servant took a little milk, along with some fruits.",
    "Especially because this servant did not desire to perform such type of severe austerity in front of a sannyāsī present here.",
    "Oh my Lord! Please excuse him for that.",
    "Please don't allow weakness into this servant's heart.",
    "If this servant was able to get a separate place or room, then he would not have to face such type of unnecessary situations.",
    "Oh merciful Lord! Please excuse this servant, as you know he has many faults and weaknesses.",
    "Please make this servant strong and determined.",
    "May Your divine potency appear within this servant, so that he becomes empowered by Your strength to serve You.",
    "Please bestow this benediction upon this servant.",
    "Oh my Lord, Gopāla! Please shower Your mercy.",
    "May this servant achieve kṛṣṇa-prema along with proper devotee association, well-wishers and companions.",
    "May this servant achieve success in the service of Śrī Śrī Guru and Gaurānga.",
    "Hare Kṛṣṇa.",
]

lines = [transliterate(c) for c in CHUNKS]
out = ROOT / "data" / "narration" / "diary_chunks.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
# display copy keeps the proper diacritics (the model read the ASCII; devotees read this)
(out.parent / "diary_display.txt").write_text("\n".join(CHUNKS) + "\n", encoding="utf-8")

for i, l in enumerate(lines, 1):
    print(f"{i:02d}  {l}")
non_ascii = [l for l in lines if any(ord(c) > 127 for c in l)]
print(f"\nwrote {out}  ({len(lines)} chunks; {len(non_ascii)} still-non-ASCII lines)")
for l in non_ascii:
    print("  NON-ASCII:", l)
