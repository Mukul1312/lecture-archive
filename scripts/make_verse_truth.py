"""Write down what the right answer is for every run we have read, so scoring stops being an
argument and becomes a measurement.

Every claim about the verse matcher in this project so far has been settled by me reading
candidates and forming a view - which is exactly how the margin error happened. This freezes
those readings into a fixture with explicit provenance and explicit uncertainty, so each change
to the scoring can be scored against it instead of debated.

The run texts are taken from the live output rather than retyped, because a fixture whose text
differs from the pipeline's by one character silently tests nothing.
"""
import json
import pathlib
import unicodedata

RUNS = pathlib.Path("data/reference/analysis/verse-runs.json")
OUT = pathlib.Path("tests/fixtures/verse_truth.json")

# Keyed by a distinctive fragment of the run. The address is what I judged correct BY READING
# the candidate against the run - see the research page and the refusal diagnosis.
CORRECT = {
    "gṛha kṣetra suta": ("SB 5.5.8", "high", "ato gṛha-kṣetra-sutāpta-vittair, read exactly"),
    "jijñāsā nārtho yaś ceha": ("SB 1.2.10", "high", "the verse's own second half"),
    "jīvasya tattva-jijñāsā": ("SB 1.2.10", "high", "both halves of the verse"),
    "śreya, lābho jīveta": ("SB 1.2.10", "high", "first half, lābho jīveta yāvatā"),
    "Śrīmad-Bhāgavatam says, jīvasya": ("SB 1.2.10", "high", "English lead-in then the verse"),
    "Śrīmad-Bhāgavatam says lābho": ("SB 1.2.10", "high", "English lead-in then half-verse"),
    "mahājano yena gataḥ": ("Cc. Madhya 17.186", "high",
                            "also printed at SB 6.3.19 and elsewhere; same verse"),
    "kāma eṣa krodha eṣa rajo": ("BG 3.37", "high", "exact, and the lecture is on BG 3.37"),
    "kāma eṣa krodha eṣa,": ("BG 3.37", "high",
                             "same verse truncated; currently loses to an unrelated song"),
    "hañā āpanāke māne tṛṇādhama": ("Cc. Antya 20.22", "high", "uttama hañā āpanāke māne"),
    "dui-prakāre sahiṣṇutā": ("Cc. Antya 20.22", "high", "exact"),
    "gharma-vṛṣṭi sahe": ("Cc. Antya 20.24", "high", "exact"),
    "amānī mānada": ("Cc. Antya 20.26", "high", "ei-mata hañā yei kṛṣṇa-nāma laya"),
    "ayācita-vṛtti": ("Cc. Ādi 17.29", "high", "exact"),
    "avaśya pāibe tabe": ("Cc. Ādi 17.33", "high", "exact"),
    "kaṁ vā dayāluṁ śaraṇaṁ": ("SB 3.2.23", "high", "kaṁ vā dayāluṁ śaraṇaṁ vrajema"),
    "pratiṣthāśā āsi": ("Krpa Koro Vaisnava Thakura", "high", "exact, scores 1.000, refused"),
    "tomāra caraṇe niṣkapaṭe": ("Krpa Koro Vaisnava Thakura", "high", "exact"),
    "bhartsana-tāḍane kāke": ("Cc. Ādi 17.27", "high",
                              "scores 1.000 at rank 1; refused on a 0.889 rival"),
    "Yāhāṅ kṛṣṇa tāhāṅ nāi": ("Cc. Madhya 22.31", "high",
                              "yāhāṅ kṛṣṇa, tāhāṅ nāhi māyāra adhikāra; the transcript even "
                              "names Caitanya-caritāmṛta"),
    "Kṛṣṇa de tomāra": ("Ohe Vaisnava Thakura", "high",
                        "kṛṣṇa se tomāra, kṛṣṇa dīte pāro, tomāra śakati āche"),
    "pāche pāche, o vaiṣṇava": ("Ohe Vaisnava Thakura", "high", "same song, adjacent lines"),
    "āmi kaṅgāl Kṛṣṇa": ("He Vaisnava Thakura , Daya Karo Mo Pai", "medium",
                         "the Hindi rendering of the same song; which printing is right is "
                         "genuinely ambiguous"),
    "rādhāyāḥ praṇaya-mahimā": ("Cc. Ādi 1.6", "medium",
                                "identical text is printed at Cc. Ādi 4.230 too, so either "
                                "address is defensible"),
    "Anugrahāya bhajanti": ("SB 3.5.3", "low",
                            "ranked second, not first; I am not confident"),
}

# Runs that must be REFUSED. Not verse quotations at all, so any address is a wrong answer.
NOT_A_QUOTATION = {
    "tri-tāpas": "a list of the three miseries, delimited by a colon",
    "ādhyātmika, ādhidaivika, ādhibhautika, three": "the same list with an English word",
    "sādhu, bhakta, Vaiṣṇava": "a list of terms",
    "rajo-guṇa, tamo-guṇa": "a list of the three modes",
    "Ṭhākur, Narottam Dās": "a list of names",
    "Gosvāmī and Ragunātha": "a list of names",
    "Rūpa Mañjari in": "a name inside an English sentence",
    "Kṛṣṇa is Rājā Rājeśvara": "an English sentence with names in it",
    "sādhu-guru is para-duḥkhe": "an English sentence",
    "niśvāsita vāṇī. But": "an English fragment",
    "You—prapaṇa": "an invocation, not a quotation",
    "Rādhārāṇī and Kṛṣṇa, yugala": "English with a phrase in it",
    "Kṛṣṇa Hare Kṛṣṇa": "the mahāmantra - fixed text, but not a verse with an address",
    "Rāma Hare Rāma": "the mahāmantra",
}

# Judged uncertain, so excluded from scoring either way rather than guessed at.
UNRESOLVED = {
    "āmi bāndhi āchi hṛdaya": "currently matched to Cc. Madhya 25.127; I flagged it uncertain "
                              "and it IS being scored, so it is a known soft spot",
    "'āmāra' bolite āre kichu nāi": "a Bhaktivinoda song line; I could not confirm it is in "
                                    "the corpus at all",
    "bhāva-grāhī janārdana": "could not confirm the source",
}


def nfc(text: str) -> str:
    """Compare on one normalisation, because these texts mix two.

    `pratiṣthāśā` written here and `pratiṣthāśā` in the pipeline's output print identically and
    are different strings: the archive's transcripts carry some diacritics precomposed and some
    decomposed. `skeleton()` never notices because it runs NFKD first, but any direct string
    comparison fails silently on characters that look the same - which is how this fixture
    matched `niraya-gāmī` and missed `pratiṣthāśā` in the very same run.
    """
    return unicodedata.normalize("NFC", text)


def classify(text: str):
    text = nfc(text)
    for fragment, (address, confidence, why) in CORRECT.items():
        if nfc(fragment) in text:
            return "correct", address, confidence, why
    for fragment, why in NOT_A_QUOTATION.items():
        if nfc(fragment) in text:
            return "refuse", None, "high", why
    for fragment, why in UNRESOLVED.items():
        if nfc(fragment) in text:
            return "unresolved", None, "none", why
    return None, None, None, None


report = json.loads(RUNS.read_text(encoding="utf-8"))
seen, rows = set(), []
for entry in report["matched"] + report["unmatched"]:
    text = entry["text"]
    if text in seen:
        continue
    seen.add(text)
    kind, address, confidence, why = classify(text)
    if kind is None:
        rows.append({"heard": text, "key": nfc(text), "slug": entry.get("slug"),
                     "verdict": "unjudged", "note": "not yet read; excluded from scoring"})
        continue
    rows.append({"heard": text, "key": nfc(text), "slug": entry.get("slug"), "verdict": kind,
                 "address": address, "confidence": confidence, "why": why})

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({
    "provenance": (
        "Judged by Claude by reading each run against its top candidates, 2026-10-11/12. "
        "NOT independently verified by the steward. Entries marked confidence 'low' or "
        "verdict 'unresolved' must not be counted as ground truth; they are recorded so that "
        "the uncertainty is visible rather than averaged away."),
    "matching": (
        "`heard` is verbatim as the pipeline emits it; `key` is the same text under NFC. "
        "MATCH ON `key`, normalising the pipeline's text the same way. These transcripts mix "
        "precomposed and decomposed diacritics, so `pratiṣthāśā` and `pratiṣthāśā` print "
        "identically and compare unequal - this fixture silently missed a run until both "
        "sides were normalised."),
    "how_to_use": (
        "A scoring change is an improvement only if it raises the count of 'correct' runs "
        "resolved to their address WITHOUT resolving any 'refuse' run to any address. Those "
        "two move in opposite directions under every loosening, which is the whole point."),
    "counts": {k: sum(1 for r in rows if r["verdict"] == k)
               for k in ("correct", "refuse", "unresolved", "unjudged")},
    "runs": rows,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: sum(1 for r in rows if r["verdict"] == k)
                  for k in ("correct", "refuse", "unresolved", "unjudged")}, indent=1))
print(f"written to {OUT}")
for r in rows:
    if r["verdict"] == "unjudged":
        print("  UNJUDGED:", r["heard"][:60])
