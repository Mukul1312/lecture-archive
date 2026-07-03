"""
lexicon.py — Stage 0 of the funnel: deterministic text normalization for the clone.

Turns diary text (with diacritics + devotional terms) into TTS-friendly input, applying a maintained
pronunciation dictionary (built once, applied to every line — not hit-and-trial). Fixes from ear-test
feedback are baked in: Gopāla -> "Gopaal" (kill the trailing "-aa"), Śrī Śrī -> "Shri Shri", etc.
Import and call normalize(text); add new fixes to LEXICON as they're discovered.

Dates are spelled out separately with spoken_date()/spoken_range() (the clone reads digits badly).
"""
import re

# Longest keys are applied first (see normalize). Keys are matched case-sensitively where it matters,
# then a diacritic fallback strips any remaining marks.
LEXICON = {
    # devotional / Sanskrit terms -> phonetic spelling the clone says with dignity
    "mahā-water": "maha water",
    "mahā": "maha",
    "Tulasī": "Tulsi",
    "kṛṣṇa-prema": "Krishna prema",
    "Kṛṣṇa-prema": "Krishna prema",
    "kṛṣṇa": "Krishna",
    "Kṛṣṇa": "Krishna",
    "Prasādam": "Prasadam",
    "prasādam": "Prasadam",
    "līlā": "leela",                 # avoid "lie-la"
    "sannyāsī": "sannyasi",
    "Gopāla's": "Gopaal's",          # ear-test: was "Gopalaa"; forces "go-PAAL"
    "Gopāla": "Gopaal",
    "Gaurāṅga": "Gauranga",
    "Śrī Śrī": "Shri Shri",          # ear-test: avoid the pause between them
    "Śrī": "Shri",
    "Mahārāja": "Maharaj",
    "Mahārāj": "Maharaj",
    "Namābhāsa": "Namabhasa",
    "Prema": "prema",

    # --- diary terms (added 2026-07-01, from the Apr/May/Jun/Jul 1975 entries) ---
    # phonetic best-guess following the Gopaal precedent (drop the trailing "-a" that
    # the clone over-articulates); NONE ear-tested yet -> refine as takes are heard.
    "Vṛndāvana Dhāma": "Vrindaavan Dhaam",
    "Vṛndāvana": "Vrindaavan",
    "Dhāma": "Dhaam",
    "Rāmanavamī": "Rama Navami",
    "Kṛṣṇa-Balarāma": "Krishna Balaram",
    "Balarāma": "Balaram",
    "Śrīla Prabhupāda": "Shrila Prabhupada",
    "Śrīla": "Shrila",
    "Prabhupāda": "Prabhupada",
    "sannyāsa dīkṣā": "sannyasa deeksha",   # "diksha" risks "DIK-sha"
    "sannyāsa": "sannyasa",
    "dīkṣā": "deeksha",
    "tridaṇḍa": "tridanda",
    "daṇḍa": "danda",
    "Īśopaniṣada": "Ishopanishad",          # capital Ī would otherwise survive the strip
    "Ghanaśyāma": "Ghanashyama",
    "Bhagavad-gītā": "Bhagavad Gita",
    "gītā": "Gita",
    "bhajana-kīrtana": "bhajan kirtan",
    "kīrtana": "kirtan",
    "śravaṇa": "shravan",
    "Ratha-yātrā": "Ratha Yatra",
    "yātrā": "yatra",
    "Svāmī": "Swami",
    "Swāmī": "Swami",
}
# typographic punctuation -> ASCII the clone reads cleanly (em/en dash -> comma-pause, curly quotes ->
# straight, ellipsis -> "..." which is what the approved calm diary used). Keeps input 7-bit clean so a
# residual non-ASCII char is a *true* unmapped-diacritic alarm, not just fancy punctuation.
_PUNCT = {"—": ",", "–": ",", "…": "...", "‘": "'", "’": "'",
          "“": '"', "”": '"', " ": " "}

# residual diacritic map (anything not covered above). Capitals included so words that START with a
# diacritic (e.g. Īśopaniṣada, Śrī) don't leave a stray mark when they slip past the LEXICON.
_DIA = str.maketrans({
    "ā": "a", "ī": "i", "ū": "u", "ṛ": "ri", "ṣ": "sh", "ṇ": "n", "ṭ": "t", "ḍ": "d",
    "ṅ": "ng", "ñ": "ny", "ś": "sh", "ḥ": "h", "ṁ": "m",
    "Ā": "A", "Ī": "I", "Ū": "U", "Ṛ": "Ri", "Ṣ": "Sh", "Ṇ": "N", "Ṭ": "T", "Ḍ": "D",
    "Ś": "Sh", "Ñ": "Ny",
})

# ordinals 1-20 + tens (compound ones like 27 -> "twenty seventh" are composed in _ord)
_ORD = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
        8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth", 13: "thirteenth",
        14: "fourteenth", 15: "fifteenth", 16: "sixteenth", 17: "seventeenth", 18: "eighteenth",
        19: "nineteenth", 20: "twentieth", 30: "thirtieth"}
_MONTH = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
          7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}


def _num(n):
    ones = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
            "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    if n < 20:
        return ones[n]
    if n < 100:
        return (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()
    return str(n)


def _ord(n):
    """1->'first', 8->'eighth', 27->'twenty seventh' (spoken ordinal for a day-of-month)."""
    if n in _ORD:
        return _ORD[n]
    tens, ones = divmod(n, 10)
    return f"{_num(tens * 10)} {_ORD[ones]}"


def _year(yyyy):
    """1975 -> 'nineteen seventy five'; 1900 -> 'nineteen hundred'."""
    hi, lo = divmod(yyyy, 100)
    return f"{_num(hi)} {_num(lo) if lo else 'hundred'}"


def spoken_date(dd, mm, yyyy, weekday=None):
    """8,5,1975,'Thursday' -> 'May eighth, nineteen seventy five, Thursday.' (spoken, not digits)."""
    s = f"{_MONTH[mm]} {_ord(dd)}, {_year(yyyy)}"
    return f"{s}, {weekday}." if weekday else f"{s}."


def spoken_range(dd1, mm1, dd2, mm2, yyyy):
    """8,7,9,7,1975 -> 'July eighth to ninth, nineteen seventy five.' (same-year date range).
    Cross-month repeats the month: 13,4,3,5,1975 -> 'April thirteenth to May third, ...'."""
    if mm1 == mm2:
        span = f"{_MONTH[mm1]} {_ord(dd1)} to {_ord(dd2)}"
    else:
        span = f"{_MONTH[mm1]} {_ord(dd1)} to {_MONTH[mm2]} {_ord(dd2)}"
    return f"{span}, {_year(yyyy)}."


def normalize(text):
    """Apply the lexicon (longest keys first) + normalize punctuation + strip residual diacritics."""
    for k in sorted(LEXICON, key=len, reverse=True):
        text = text.replace(k, LEXICON[k])
    for k, v in _PUNCT.items():
        text = text.replace(k, v)
    text = text.translate(_DIA)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)   # no space before punctuation (em-dash->comma left one)
    text = re.sub(r"[\s,;:–-]+$", "", text)         # a spoken chunk shouldn't end on a dangling comma/dash
    return text


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [
        "This servant took a vow not to eat anything at night except a little mahā-water with Tulasī.",
        "Oh my Lord, Gopāla! Please shower Your mercy.",
        "...in the service of Śrī Śrī Guru and Gaurāṅga. Hare Kṛṣṇa.",
        "For receiving complete and uninterrupted kṛṣṇa-prema.",
        "By the mercy of Gopāla, these days passed in Śrī Vṛndāvana Dhāma.",
        "On this day this servant accepted the daṇḍa (tridaṇḍa) — sannyāsa dīkṣā.",
        "Śrī Śrī Īśopaniṣada Hindi printing is done; open an ISKCON centre in Bhubaneswar.",
        "a branch of ISKCON at Gadeigiri ... performing śravaṇa and kīrtana, bhajana-kīrtana there.",
        "met Śrīla Prabhupāda at Śrī Kṛṣṇa-Balarāma temple; tomorrow is Ratha-yātrā at Puri.",
        "to teach and preach about the Bhagavad-gītā to the devotees.",
    ]
    for t in tests:
        print(f"IN : {t}\nOUT: {normalize(t)}\n")
    print(spoken_date(8, 5, 1975, "Thursday"))     # May 8 entry
    print(spoken_date(4, 5, 1975, "Sunday"))       # May 4 entry
    print(spoken_date(1, 6, 1975))                 # Jun 1 entry (no weekday)
    print(spoken_range(8, 7, 9, 7, 1975))          # Jul 8-9 entry
    print(spoken_range(13, 4, 27, 4, 1975))        # Apr 13-27 header
