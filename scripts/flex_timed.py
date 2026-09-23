"""flex, with timestamps.

flex is the archive's only working Bengali recogniser and the reason this matters: it returns
6,175 words in one string with no timing of any kind, which is exactly the thing read-along
playback cannot do without.

The timings are not missing, though. They are discarded. `transcribe_long` cuts the audio at
pauses into pieces of at most thirty seconds, decodes each one separately, and then ends with
`" ".join(out)` - at which point it knows which piece produced which words and throws that
away. Everything below exists to keep it.

Keeping it makes alignment easy rather than hard. The alternative - aligning a 6,175-word blob
against seventy minutes of audio - runs into a Viterbi backtrack matrix of frames by letters
that wants tens of gigabytes, and into the question of which words belong to which chunk, which
has no good answer. A piece of at most thirty seconds whose words are already known has neither
problem: it aligns in under a second and no boundary is ever guessed.

The decoding itself is flex's own, imported rather than reimplemented, so the text this
produces is the text the bake-off scored and not a near-miss.

    .venv-indic/Scripts/python.exe -m scripts.flex_timed AUDIO.mp3 OUT.json --lang bn --mode mixed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch

from scripts.forced_align import SAMPLE_RATE, align, emissions, to_seconds

REPO = Path(__file__).resolve().parents[1]
FLEX = REPO / "data/models/indic-transcribe-flex"


@dataclass
class Segment:
    """One pause-bounded piece of audio, and what flex heard in it."""

    start: float   # seconds into the recording
    end: float
    text: str


def _flex():
    """flex's own modules. Imported here so nothing else has to know where they live."""
    if str(FLEX) not in sys.path:
        sys.path.insert(0, str(FLEX))
    from indic_transcribe import IndicTranscribe          # noqa: E402
    from long_form import CHUNK_MAX_NEW_TOKENS, _decode_guarded, split_on_silence  # noqa: E402
    return IndicTranscribe, split_on_silence, _decode_guarded, CHUNK_MAX_NEW_TOKENS


def load_audio(path: str) -> torch.Tensor:
    """16 kHz mono, downmixed and resampled exactly as flex does it."""
    import soundfile as sf
    import torchaudio
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    wav = torch.as_tensor(data).mean(dim=1)
    if rate != SAMPLE_RATE:
        wav = torchaudio.functional.resample(wav, rate, SAMPLE_RATE)
    return wav


def transcribe_segments(asr, wav: torch.Tensor, lang: str, mode: str = "native",
                        **kw) -> list[Segment]:
    """What `transcribe_long` does, stopping one line before it forgets where it was.

    The cutting, the skipping of pieces under a tenth of a second and the token budget are all
    flex's, copied deliberately: a piece decoded differently here would not be the text the
    bake-off measured.
    """
    _, split_on_silence, decode, chunk_tokens = _flex()
    kw.setdefault("max_new_tokens", chunk_tokens)

    segments = []
    for first, last in split_on_silence(wav):
        piece = wav[first:last]
        if piece.numel() < 1600:               # under 0.1 s; flex skips these
            continue
        text = decode(asr, piece, lang, mode, kw)
        if text and text.strip():
            segments.append(Segment(first / SAMPLE_RATE, last / SAMPLE_RATE, text.strip()))
    return segments


def time_words(wav: torch.Tensor, segments: list[Segment], to_iast=None) -> list[dict]:
    """Give every word flex produced a start and an end, by aligning it inside its own piece.

    Each piece is short and its words are known, so this is the easy case of forced alignment
    and not the hard one. A piece that cannot be aligned - too many words for its audio, or
    nothing alignable in the text - is reported rather than dropped, because a missing word is
    invisible in the output and a missing piece is not.
    """
    timed, failures = [], []
    for index, segment in enumerate(segments):
        text = to_iast(segment.text) if to_iast else segment.text
        words = text.split()
        piece = wav[int(segment.start * SAMPLE_RATE):int(segment.end * SAMPLE_RATE)]
        try:
            log_probs, seconds_per_frame = emissions(piece)
            spans = to_seconds(align(log_probs, words), seconds_per_frame, offset=segment.start)
        except Exception as exc:
            failures.append({"segment": index, "why": str(exc)[:200]})
            continue
        timed.extend({"word": s.word, "start": round(s.start, 3), "end": round(s.end, 3),
                      "score": round(s.score, 4), "segment": index} for s in spans)
    if failures:
        print(f"  {len(failures)} of {len(segments)} segments could not be aligned: "
              f"{failures[:2]}")
    return timed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio")
    parser.add_argument("out")
    parser.add_argument("--lang", default="bn")
    parser.add_argument("--mode", default="mixed")
    parser.add_argument("--until", type=float, default=None,
                        help="stop after this many seconds of audio, for a trial run")
    args = parser.parse_args()

    IndicTranscribe, _, _, _ = _flex()
    wav = load_audio(args.audio)
    if args.until:
        wav = wav[:int(args.until * SAMPLE_RATE)]
    print(f"{wav.size(0) / SAMPLE_RATE / 60:.1f} minutes of audio", flush=True)

    started = time.time()
    asr = IndicTranscribe.from_pretrained(str(FLEX))
    segments = transcribe_segments(asr, wav, args.lang, args.mode)
    decoded = time.time()
    print(f"{len(segments)} segments decoded in {decoded - started:.0f}s", flush=True)

    # The bake-off converts flex's Indic-script runs to IAST before scoring, so the words
    # timed here are the words that were measured there.
    sys.path.insert(0, str(REPO / "data/research/prabhupadavani"))
    try:
        from run_flex import to_iast
    except ImportError:
        to_iast = None
        print("  run_flex.to_iast unavailable; timing flex's raw output", flush=True)
    words = time_words(wav, segments, to_iast)

    Path(args.out).write_text(json.dumps({
        "what_this_is": "flex's transcript with a start and end for every word.",
        "how": "flex's own pause-cut segments, then CTC forced alignment inside each one.",
        "audio": args.audio,
        "lang": args.lang,
        "mode": args.mode,
        "segments": [asdict(s) for s in segments],
        "words": words,
        "decode_seconds": round(decoded - started, 1),
        "align_seconds": round(time.time() - decoded, 1),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(words):,} words timed, aligned in {time.time() - decoded:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
