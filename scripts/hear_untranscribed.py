"""What is in the parts nobody wrote down?

Two claims in this project rest on stretches of audio that no transcript covers, and both were
made from loudness alone - which says something is there, not what it is.

The Melbourne reference skips 11.4 minutes at the head and 12.5 at the tail of a 92.7-minute
recording, and those stretches are *louder* than the class. I called them kirtan. That was an
inference from a number.

Six archive lectures stop while the recording continues, the worst leaving 29.5 minutes. I said
he is still speaking. Also an inference.

This cuts those stretches out and runs a recogniser over them, so the question is settled by
what was actually said rather than by how loud it was. It also writes the clips beside the text,
because a machine transcript of chanting is not reliable and the steward can listen.

    .venv-transcribe/Scripts/python.exe scripts/hear_untranscribed.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data/reference/analysis/untranscribed"
MELBOURNE = REPO / "data/reference/90-11-14 SB12.10.2 MEL 90-85.mp3"
ALIGNED = REPO / "data/reference/analysis/archive-alignment"

# Long enough to tell chanting from speech, short enough to listen to without losing the morning.
SAMPLE_SECONDS = 90.0


@dataclass
class Stretch:
    """A piece of a recording that no transcript accounts for."""

    label: str
    source: Path
    start: float
    end: float
    why: str


def seconds_of(path: Path) -> float:
    """A recording's length, asked of ffprobe - the one audio tool present in every venv here."""
    probe = shutil.which("ffprobe")
    if not probe:
        # ffprobe ships beside ffmpeg. Deriving it by replacing the word in the path does not
        # work: this install lives in "ffmpeg-8.1-essentials_build/bin/ffmpeg", so a plain
        # replace rewrites the directory too and the file vanishes.
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("neither ffprobe nor ffmpeg is on PATH")
        candidate = Path(ffmpeg).with_name("ffprobe.exe")
        if not candidate.exists():
            candidate = Path(ffmpeg).with_name("ffprobe")
        probe = str(candidate)
    result = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                            check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def melbourne_stretches() -> list[Stretch]:
    timings = json.loads((REPO / "data/reference/analysis/word-timings-mmsfa.json")
                         .read_text(encoding="utf-8"))
    words = sorted((w for cue in timings["cues"] for w in cue["words"]),
                   key=lambda w: w["start"])
    duration = seconds_of(MELBOURNE)
    return [
        Stretch("melbourne-head", MELBOURNE, 0.0, words[0]["start"],
                "before the verified reference begins"),
        Stretch("melbourne-tail", MELBOURNE, words[-1]["end"], duration,
                "after the verified reference ends"),
    ]


def archive_stretches(minimum: float = 300.0) -> list[Stretch]:
    out = []
    for path in sorted(ALIGNED.glob("*.json")):
        if path.name == "SUMMARY.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if not record["words"]:
            continue
        last = record["words"][-1]["end"]
        left = record["audio_seconds"] - last
        if left < minimum:
            continue
        audio = REPO / "data/lectures" / record["slug"] / "audio.mp3"
        if audio.exists():
            out.append(Stretch(record["slug"][:44], audio, last, record["audio_seconds"],
                               f"transcript stops here, {left / 60:.1f} min of recording left"))
    return out


def cut(stretch: Stretch, destination: Path, seconds: float | None = None) -> bool:
    """Extract a stretch as 16 kHz mono wav. ffmpeg, because some of these files are damaged."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not on PATH")
    length = min(seconds or (stretch.end - stretch.start), stretch.end - stretch.start)
    if length <= 1.0:
        return False
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-err_detect", "ignore_err", "-ss", str(stretch.start),
                    "-t", str(length), "-i", str(stretch.source),
                    "-ac", "1", "-ar", "16000", str(destination)],
                   check=True, capture_output=True)
    return destination.exists()


def transcribe(path: Path, model) -> str:
    """What a recogniser makes of the clip.

    `condition_on_previous_text=False` matters here more than usual. These stretches are the
    ones nobody transcribed, and a good share of them are chanting - on which Whisper loops,
    repeating a phrase until the token budget runs out and taking minutes over ninety seconds of
    audio. Cutting the conditioning stops the loop. The looping is itself a signal, so it is
    reported rather than hidden.
    """
    segments, _ = model.transcribe(str(path), beam_size=1, vad_filter=False,
                                   condition_on_previous_text=False)
    heard = " ".join(s.text.strip() for s in segments).strip()
    words = heard.split()
    grams = [tuple(words[i:i + 4]) for i in range(len(words) - 3)]
    repetition = (len(grams) - len(set(grams))) / max(1, len(grams))
    if repetition > 0.5:
        heard = f"[recogniser looped, {repetition:.0%} repeated - usually chanting] {heard}"
    return heard


def main() -> None:
    from faster_whisper import WhisperModel

    OUT.mkdir(parents=True, exist_ok=True)
    stretches = melbourne_stretches() + archive_stretches()
    print(f"{len(stretches)} untranscribed stretches to listen to\n", flush=True)

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    results = []
    for stretch in stretches:
        clip = OUT / f"{stretch.label}.wav"
        print(f"{stretch.label}  ({stretch.start / 60:.1f}-{stretch.end / 60:.1f} min)", flush=True)
        if not cut(stretch, clip, SAMPLE_SECONDS):
            continue
        heard = transcribe(clip, model)
        results.append({
            "label": stretch.label, "why": stretch.why,
            "source": stretch.source.name,
            "from_minute": round(stretch.start / 60, 1),
            "to_minute": round(stretch.end / 60, 1),
            "minutes_untranscribed": round((stretch.end - stretch.start) / 60, 1),
            "clip": clip.name,
            "sampled_seconds": SAMPLE_SECONDS,
            "whisper_heard": heard,
        })
        print(f"    {heard[:150]}\n", flush=True)

    (OUT / "heard.json").write_text(json.dumps(results, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
    page = write_page(results)
    print(f"{len(results)} clips and transcripts -> {OUT}")
    print(f"open this to listen: {page}")




PAGE = """<!doctype html>
<meta charset="utf-8"><title>What nobody wrote down</title>
<style>
 :root {{ color-scheme: light dark; --line: #8883; }}
 body {{ font: 16px/1.55 system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; }}
 h1 {{ font-size: 1.4rem; margin-bottom: .3rem; }}
 .lede {{ color: #888; margin-top: 0; }}
 .item {{ border-top: 1px solid var(--line); padding: 1.1rem 0; }}
 .label {{ font-weight: 600; }}
 .why {{ color: #888; font-size: .9rem; }}
 audio {{ width: 100%; margin: .6rem 0; }}
 .heard {{ background: #8881; padding: .6rem .8rem; border-radius: .4rem; font-size: .95rem; }}
 .heard b {{ font-weight: 600; color: #888; display: block; font-size: .8rem; margin-bottom: .25rem; }}
</style>
<h1>What nobody wrote down</h1>
<p class=lede>Stretches of audio no transcript covers. The text below each player is what
Whisper heard in the first {sampled:.0f} seconds &mdash; a machine, and an unreliable one on
chanting, so trust your ears over it.</p>
{items}
"""

ITEM = """<div class=item>
 <div class=label>{label}</div>
 <div class=why>{why} &mdash; {from_minute}&ndash;{to_minute} min of {source}
 ({minutes} minutes with no transcript)</div>
 <audio controls preload=none src="{clip}"></audio>
 <div class=heard><b>whisper heard</b>{heard}</div>
</div>"""


def write_page(results: list[dict]) -> Path:
    """A page beside the clips, so the question can be settled by listening.

    Kept local rather than published: these are the archive's own recordings of a departed
    teacher, and putting them on a public URL is not a decision this script should make.
    """
    items = "".join(ITEM.format(
        label=r["label"], why=r["why"], from_minute=r["from_minute"], to_minute=r["to_minute"],
        source=r["source"], minutes=r["minutes_untranscribed"], clip=r["clip"],
        heard=(r["whisper_heard"][:1200] or "&mdash; nothing recognisable &mdash;"))
        for r in results)
    page = OUT / "listen.html"
    page.write_text(PAGE.format(sampled=SAMPLE_SECONDS, items=items), encoding="utf-8")
    return page

if __name__ == "__main__":
    main()
