"""Run the hosted recognisers over archive lectures, one lecture at a time.

This is the cheap half of testing whether Melbourne's ranking survives a different decade and
venue. ElevenLabs and Sarvam cost cents per hour and take minutes, against days of laptop for
the local three - the inversion of the usual instinct, and the reason to fire this first.

**It sends audio to two vendors.** Rights-holder permission for transcription is held, but the
retention positions differ and are worth restating every time this runs: ElevenLabs' Zero
Retention Mode is enterprise-only, and Sarvam publishes no retention page at all. So the default
is `plan`, which sends nothing and prints exactly what would go and what it would cost.

Scope defaults to the lectures the span manifest names in `grade_on_these_first` - the
transcripts recording no other speaker, where a missing questioner turn cannot inflate anyone's
error rate.

    python scripts/hosted_run.py plan
    python scripts/hosted_run.py send --service elevenlabs
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPANS = REPO / "data/reference/analysis/scoreable-spans.json"
OUT = REPO / "data/reference/analysis/hosted"
KEYTERMS = REPO / "data/reference/keyterms-50.txt"

# From this repo's own api-tier-pricing-2026-08-27.md, per hour of audio.
PRICE_PER_HOUR = {"elevenlabs": 0.22, "sarvam": 0.314}


def secret(name: str) -> str:
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        match = re.match(rf"\s*{name}\s*=\s*['\"]?([^'\"\s]+)", line)
        if match:
            return match.group(1)
    raise SystemExit(f"{name} not found in .env.local")


def keyterms() -> list[str]:
    """The fifty names that cut ElevenLabs' Indic error by eight points inside the recogniser."""
    return [t.strip() for t in KEYTERMS.read_text(encoding="utf-8").splitlines() if t.strip()]


def chosen(solo_only: bool = True, limit: int | None = None) -> list[dict]:
    manifest = json.loads(SPANS.read_text(encoding="utf-8"))
    wanted = set(manifest["grade_on_these_first"]["slugs"]) if solo_only else None
    picked = [l for l in manifest["detail"]
              if not l["duplicate_of"] and (wanted is None or l["slug"] in wanted)]
    return picked[:limit]


def already_done(slug: str, service: str) -> bool:
    return (OUT / service / f"{slug}.json").exists()


def run_elevenlabs(audio: Path, terms: list[str]) -> dict:
    import requests
    fields = [("model_id", (None, "scribe_v2")), ("timestamps_granularity", (None, "word")),
              ("diarize", (None, "false")), ("no_verbatim", (None, "false")),
              ("file", (audio.name, audio.read_bytes(), "audio/mpeg"))]
    fields += [("keyterms", (None, t)) for t in terms]
    response = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                             headers={"xi-api-key": secret("ELEVENLABS_API_KEY")},
                             files=fields, timeout=3600)
    response.raise_for_status()
    payload = response.json()
    return {
        "text": payload["text"],
        "words": [{"w": w["text"], "s": w.get("start"), "e": w.get("end"), "p": w.get("logprob")}
                  for w in payload.get("words", []) if w.get("type", "word") == "word"],
        "detected_language": payload.get("language_code"),
    }


def run_sarvam(audio: Path, terms: list[str], keep_raw: Path) -> dict:
    """Sarvam's batch flow, with the raw payload kept.

    The bake-off's parser recorded Sarvam's words with `s: None, e: None`, which is why Sarvam
    has never been span-scored. `with_timestamps=True` is requested, so the times may simply sit
    under a shape the parser did not read - keeping the raw output is how that gets settled
    rather than assumed.
    """
    from sarvamai import SarvamAI
    client = SarvamAI(api_subscription_key=secret("SARVAM_API_KEY"))
    kwargs = dict(model="saaras:v4", mode="verbatim", language_code="en-IN", with_timestamps=True)
    if terms:
        kwargs["keyterms"] = terms
    job = client.speech_to_text_job.create_job(**kwargs)
    job.upload_files(file_paths=[str(audio)])
    job.start()
    job.wait_until_complete()
    keep_raw.mkdir(parents=True, exist_ok=True)
    job.download_outputs(output_dir=str(keep_raw))

    text, words = "", []
    for path in sorted(keep_raw.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        text += " " + (payload.get("transcript") or payload.get("text") or "")
        stamps = payload.get("timestamps") or {}
        labels = stamps.get("words") or []
        starts, ends = stamps.get("start_time_seconds") or [], stamps.get("end_time_seconds") or []
        for index, word in enumerate(labels):
            words.append({"w": word,
                          "s": starts[index] if index < len(starts) else None,
                          "e": ends[index] if index < len(ends) else None, "p": None})
    return {"text": text.strip(), "words": words, "detected_language": "en-IN"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "send"])
    parser.add_argument("--service", choices=["elevenlabs", "sarvam", "both"], default="both")
    parser.add_argument("--all", action="store_true",
                        help="every aligned lecture, not only the solo ones")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    lectures = chosen(solo_only=not args.all, limit=args.limit)
    hours = sum(l["audio_seconds"] for l in lectures) / 3600
    services = ["elevenlabs", "sarvam"] if args.service == "both" else [args.service]

    print(f"{len(lectures)} lectures, {hours:.2f} hours of audio")
    for service in services:
        pending = [l for l in lectures if not already_done(l["slug"], service)]
        cost = sum(l["audio_seconds"] for l in pending) / 3600 * PRICE_PER_HOUR[service]
        print(f"  {service:12} {len(pending):>2} to send, ${cost:.2f}")
    print(f"  {'TOTAL':12} {'':>2}    ${sum(sum(l['audio_seconds'] for l in lectures if not already_done(l['slug'], s)) / 3600 * PRICE_PER_HOUR[s] for s in services):.2f}")

    if args.stage == "plan":
        print("\nThis would send the audio of these lectures to the named vendors:")
        for lecture in lectures:
            print(f"   {lecture['audio_seconds']/60:>5.0f} min  {lecture['slug'][:58]}")
        print("\n⚠ ElevenLabs Zero Retention is enterprise-only; Sarvam publishes no retention "
              "page.\n  Nothing has been sent. Re-run with `send` to proceed.")
        return

    terms = keyterms()
    for service in services:
        (OUT / service).mkdir(parents=True, exist_ok=True)
        for index, lecture in enumerate(lectures, 1):
            slug = lecture["slug"]
            if already_done(slug, service):
                print(f"[{service} {index}/{len(lectures)}] {slug[:44]} - already done", flush=True)
                continue
            audio = REPO / lecture["audio"]
            print(f"[{service} {index}/{len(lectures)}] {slug[:44]} "
                  f"({lecture['audio_seconds']/60:.0f} min)", flush=True)
            started = time.time()
            try:
                if service == "elevenlabs":
                    result = run_elevenlabs(audio, terms)
                else:
                    result = run_sarvam(audio, terms, OUT / service / f"{slug}-raw")
            except Exception as exc:
                print(f"    FAILED {type(exc).__name__}: {str(exc)[:110]}", flush=True)
                continue
            timed = sum(1 for w in result["words"] if w.get("s") is not None)
            record = {**result, "slug": slug, "service": service, "keyterms": len(terms),
                      "audio_seconds": lecture["audio_seconds"],
                      "wall_seconds": round(time.time() - started, 1),
                      "words_total": len(result["words"]), "words_with_times": timed}
            (OUT / service / f"{slug}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"    {len(result['words']):,} words, {timed:,} with timestamps, "
                  f"{time.time()-started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
