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

Run it with `.venv-api`, which is the only environment here holding both `requests` and the
Sarvam SDK. Any other interpreter reaches the upload and then fails on the import, which wastes
nothing but reads exactly like a refusal from Sarvam.

    .venv-api/Scripts/python.exe -m scripts.hosted_run plan
    .venv-api/Scripts/python.exe -m scripts.hosted_run send --service elevenlabs
    .venv-api/Scripts/python.exe -m scripts.hosted_run send --service sarvam --slug SLUG
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

# Measured twice, and they agree. ElevenLabs' own quota error priced a 61.0-minute lecture
# with 50 keyterms at 4,865 credits, which is 79.8 a minute; two lectures sent afterwards,
# 114.6 minutes together, drew 9,168, which is 80.0. The same hour without keyterms costs
# about 4,054, so the fifty names that bought eight points of Indic accuracy also cost a fifth
# more - a line the $760 corpus estimate did not have.
CREDITS_PER_MINUTE = 80.0

# Sarvam accepted 60.8 minutes and refused 86.3. It is duration and not size: the 92-minute
# refusal is 71 MB, smaller than the 74 MB file that went through. Where between the two the
# wall actually sits is unmeasured, so the ceiling here is the longest proven success and
# nothing is claimed above it.
SARVAM_PROVEN_CEILING = 61.0 * 60

# A gap between lectures. Nine large uploads back to back tripped ElevenLabs' limiter on the
# first run; nothing here is urgent enough to push a stranger's servers that hard.
PAUSE_BETWEEN = 15.0


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


class HostedFailure(RuntimeError):
    """A refusal from a hosted recogniser, carrying the sentence that explains it.

    `requests.raise_for_status()` raises a message built from the status line and throws the
    body away. The body is the only place the reason lives, and on this API the reason and the
    status disagree: quota exhaustion arrives as 401.
    """

    def __init__(self, status: int, body: str):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}: {body[:400]}")


def retryable(exc: Exception) -> bool:
    """Is waiting a plausible fix for this failure?

    **401 is never retried.** It was read as rate limiting and it is not: ElevenLabs answers an
    exhausted quota with 401, and the first run spent five escalating waits per lecture asking
    an empty account for 4,865 credits it did not have. A bad key is the other thing 401 means
    here, and patience does not fix that either - the pre-flight balance check below tells the
    two apart before a byte is uploaded.

    400 is not retried for the same reason: Sarvam refuses over-long audio with it, and the
    file will not get shorter. 429 and 5xx are genuinely transient, and waiting on them is also
    the polite thing - these are somebody else's servers and the archive is not in a hurry.
    """
    status = getattr(exc, "status", None)
    if status is None:
        return any(code in str(exc) for code in ("429", "500", "502", "503", "504"))
    return status == 429 or 500 <= status < 600


def with_backoff(call, attempts: int = 5, first_wait: float = 20.0):
    """Retry a hosted call while retrying could help, waiting longer each time."""
    import time as clock
    wait = first_wait
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            if attempt == attempts - 1 or not retryable(exc):
                raise
            print(f"    {type(exc).__name__} - waiting {wait:.0f}s then retrying "
                  f"({attempt + 2} of {attempts})", flush=True)
            clock.sleep(wait)
            wait *= 2
    raise RuntimeError("unreachable")


def remaining_credits(limit: int, subscription_counter: int, usage: dict) -> int:
    """How much of the allowance is left, from the two meters that disagree.

    `/v1/user/subscription` carries `character_count`, which is the obvious place to look and
    is the wrong one: it still read **0** after two lectures had spent 9,168 credits of Scribe.
    `/v1/usage/character-stats` had the 9,168. So the counter tracks something else, or lags,
    and either way believing it would send an hour of audio at an account that cannot pay.

    Taking the **larger** of the two is the safe direction: over-reporting spend skips a
    lecture that could have gone, and under-reporting it sends one that gets refused.
    """
    spent = sum(sum(series) for series in usage.values())
    return int(limit - max(spent, subscription_counter))


def period_start_ms(next_reset_unix: int) -> int:
    """The start of the UTC day on which the current allowance began.

    The allowance refills on the same day each month, so the period began one calendar month
    before the next reset - clamped to the month's last day, since 31 March has no 31 February.
    Counting from 31 days before the next reset instead reached a day into the previous period
    and charged its 9,168 credits again, reporting -307 for an account holding 8,861. The whole
    reset day is counted, because the usage report buckets by UTC day and spend in the hours
    before a reset is indistinguishable from spend after it - overcounting is the safe side.
    """
    import calendar
    import datetime
    reset = datetime.datetime.fromtimestamp(next_reset_unix, datetime.timezone.utc)
    year, month = (reset.year, reset.month - 1) if reset.month > 1 else (reset.year - 1, 12)
    day = min(reset.day, calendar.monthrange(year, month)[1])
    start = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
    return int(start.timestamp() * 1000)


def credits_left() -> int:
    """What the ElevenLabs account can actually pay for, asked before anything is sent.

    Free and instant, and it is the check whose absence turned one exhausted quota into three
    contradictory diagnoses. A 20-second probe returning 200 proves nothing about an hour-long
    file: it succeeded because it cost 22 credits and 90 remained.
    """
    import requests
    headers = {"xi-api-key": secret("ELEVENLABS_API_KEY")}
    subscription = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                                headers=headers, timeout=60)
    if subscription.status_code != 200:
        raise HostedFailure(subscription.status_code, subscription.text)
    plan = subscription.json()

    # The allowance refills monthly, so the window is the current period and nothing before it.
    stats = requests.get("https://api.elevenlabs.io/v1/usage/character-stats", headers=headers,
                         params={"start_unix": period_start_ms(
                                     int(plan["next_character_count_reset_unix"])),
                                 "end_unix": int(time.time() * 1000)}, timeout=60)
    if stats.status_code != 200:
        raise HostedFailure(stats.status_code, stats.text)
    return remaining_credits(int(plan["character_limit"]), int(plan["character_count"]),
                             stats.json().get("usage", {}))


def fits_the_budget(lectures: list[dict], credits: float,
                    paired_with_other_service: set[str]) -> list[dict]:
    """Which lectures to send when the account holds less than the corpus needs.

    Two rules, in order. **A lecture the other recogniser has already transcribed goes first**,
    because the output of this run is a comparison and a lecture only one system has read
    compares with nothing. Then **the longest that still fits**, because within the paired set
    every lecture is equally comparable and the long ones carry more speech per credit.

    A lecture that cannot fit is skipped rather than attempted. Attempting it is what produced
    the 401 storm: nine uploads sent at an account holding ninety credits.
    """
    ordered = sorted(lectures,
                     key=lambda l: (l["slug"] not in paired_with_other_service,
                                    -l["audio_seconds"]))
    chosen, budget = [], credits
    for one in ordered:
        cost = one["audio_seconds"] / 60 * CREDITS_PER_MINUTE
        if cost <= budget:
            chosen.append(one)
            budget -= cost
    return chosen


def too_long_for_sarvam(lecture: dict) -> bool:
    """Above the longest duration Sarvam is known to accept, so do not spend a job finding out."""
    return lecture["audio_seconds"] > SARVAM_PROVEN_CEILING


def run_elevenlabs(audio: Path, terms: list[str]) -> dict:
    import requests
    fields = [("model_id", (None, "scribe_v2")), ("timestamps_granularity", (None, "word")),
              ("diarize", (None, "false")), ("no_verbatim", (None, "false")),
              ("file", (audio.name, audio.read_bytes(), "audio/mpeg"))]
    fields += [("keyterms", (None, t)) for t in terms]
    response = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
                             headers={"xi-api-key": secret("ELEVENLABS_API_KEY")},
                             files=fields, timeout=3600)
    if response.status_code != 200:
        raise HostedFailure(response.status_code, response.text)
    payload = response.json()
    return {
        "text": payload["text"],
        "words": [{"w": w["text"], "s": w.get("start"), "e": w.get("end"), "p": w.get("logprob")}
                  for w in payload.get("words", []) if w.get("type", "word") == "word"],
        "detected_language": payload.get("language_code"),
        "unit": "word",
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
    # Sarvam's entries are SEGMENTS of ten to sixteen seconds, not words, and saying so here
    # is the difference between "182 words for a 46-minute lecture" - which would read as a
    # catastrophic failure in any comparison table - and 182 segments carrying 5,322 words.
    return {"text": text.strip(), "words": words, "detected_language": "en-IN",
            "unit": "segment"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "send"])
    parser.add_argument("--service", choices=["elevenlabs", "sarvam", "both"], default="both")
    parser.add_argument("--all", action="store_true",
                        help="every aligned lecture, not only the solo ones")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--slug", action="append", default=None,
                        help="one named lecture; repeat for several")
    args = parser.parse_args()

    lectures = chosen(solo_only=not args.all and not args.slug, limit=args.limit)
    if args.slug:
        wanted = set(args.slug)
        lectures = [l for l in lectures if l["slug"] in wanted]
        missing = wanted - {l["slug"] for l in lectures}
        if missing:
            raise SystemExit(f"not in the span manifest: {', '.join(sorted(missing))}")
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
        pending = [l for l in lectures if not already_done(l["slug"], service)]

        if service == "sarvam":
            for lecture in pending:
                if too_long_for_sarvam(lecture):
                    print(f"  skipping {lecture['slug'][:44]} - "
                          f"{lecture['audio_seconds']/60:.0f} min is above the "
                          f"{SARVAM_PROVEN_CEILING/60:.0f} min Sarvam is known to accept; "
                          f"it needs chunk-and-stitch, not another attempt", flush=True)
            pending = [l for l in pending if not too_long_for_sarvam(l)]

        if service == "elevenlabs" and pending:
            balance = credits_left()
            other = {p.stem for p in (OUT / "sarvam").glob("*.json")}
            affordable = fits_the_budget(pending, balance, other)
            print(f"  {balance:,} credits in the account "
                  f"({balance/CREDITS_PER_MINUTE:.0f} min of Scribe with {len(terms)} keyterms)",
                  flush=True)
            for lecture in pending:
                if lecture not in affordable:
                    print(f"  skipping {lecture['slug'][:44]} - "
                          f"{lecture['audio_seconds']/60*CREDITS_PER_MINUTE:,.0f} credits needed, "
                          f"not enough left", flush=True)
            # Cheapest first among the affordable, so an estimate that is low costs the
            # smallest lecture rather than the largest.
            pending = sorted(affordable, key=lambda l: l["audio_seconds"])

        for index, lecture in enumerate(pending, 1):
            slug = lecture["slug"]
            audio = REPO / lecture["audio"]
            print(f"[{service} {index}/{len(pending)}] {slug[:44]} "
                  f"({lecture['audio_seconds']/60:.0f} min)", flush=True)
            time.sleep(PAUSE_BETWEEN)
            started = time.time()
            try:
                if service == "elevenlabs":
                    result = with_backoff(lambda: run_elevenlabs(audio, terms))
                else:
                    result = with_backoff(
                        lambda: run_sarvam(audio, terms, OUT / service / f"{slug}-raw"))
            except Exception as exc:
                # The whole message, not a 110-character stub: the reason lives in the body.
                print(f"    FAILED {type(exc).__name__}: {exc}", flush=True)
                if "quota_exceeded" in str(exc):
                    print("    the account is empty - stopping rather than asking again",
                          flush=True)
                    break
                continue
            timed = sum(1 for w in result["words"] if w.get("s") is not None)
            unit = result.get("unit", "word")
            record = {**result, "slug": slug, "service": service, "keyterms": len(terms),
                      "audio_seconds": lecture["audio_seconds"],
                      "wall_seconds": round(time.time() - started, 1),
                      "units_total": len(result["words"]), "units_with_times": timed,
                      "text_words": len(result["text"].split())}
            (OUT / service / f"{slug}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"    {len(result['words']):,} {unit}s, {timed:,} with timestamps, "
                  f"{record['text_words']:,} words of text, "
                  f"{time.time()-started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
