"""When each word was spoken, given a transcript that already says what was spoken.

Recognition and alignment are different questions. Every system in the bake-off answers the
first. Only some answer the second, and the one the archive depends on for Bengali - `flex` -
answers it not at all: 6,175 words in a single blob with no timestamps anywhere. Read-along
playback, which is the product, needs the second answer for every word.

Forced alignment supplies it. The transcript is treated as known and the only unknown is
*where*, which turns a hard recognition problem into a cheap search: a CTC acoustic model
scores every symbol at every frame, and Viterbi finds the one path through those frames that
spells the transcript. Because the text is given, the model never has to be right about what
was said - which is why this can work on 1980s cassette audio that defeats recognition, and on
Sanskrit that Whisper has never once been trained to transcribe.

The acoustic model is torchaudio's MMS_FA, wav2vec2 fine-tuned across 1,100+ languages onto a
single romanised alphabet. That alphabet is why it suits this archive: our reference is already
romanised, so English, Sanskrit and Bengali all go through one model, and there is no
per-language aligner to find for languages that have none.

The alphabet is also the whole difficulty. It is twenty-nine symbols, and the transcript is
IAST with diacritics, hyphens, digits and avagrahas, none of which the model has seen. Nothing
here fails loudly if that mapping is wrong - a dropped symbol just slides every later word, and
the page highlights the wrong word for the rest of the lecture. Hence the care, and the tests.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np
import soundfile as sf
import torch
import torchaudio

SAMPLE_RATE = 16_000  # what MMS_FA expects; the lecture masters are 44.1 kHz stereo

# MMS_FA's alphabet, as `torchaudio.pipelines.MMS_FA.get_dict()` returns it. It is copied here
# so the tokenising rules can be tested without a 1.2 GB download; `check_dictionary()` proves
# the copy still matches the installed model.
DICTIONARY: dict[str, int] = {
    "-": 0, "a": 1, "i": 2, "e": 3, "n": 4, "o": 5, "u": 6, "t": 7, "s": 8, "r": 9,
    "m": 10, "k": 11, "l": 12, "d": 13, "g": 14, "h": 15, "y": 16, "b": 17, "p": 18,
    "w": 19, "c": 20, "v": 21, "j": 22, "z": 23, "f": 24, "'": 25, "q": 26, "x": 27,
    "*": 28,
}
BLANK = 0
STAR = "*"

# Everything the model can be asked to find. '-' is blank and '*' is the wildcard, so neither
# is ever a target: they are control symbols that happen to live in the same table.
_ALIGNABLE = frozenset(set(DICTIONARY) - {"-", STAR})


def check_dictionary() -> None:
    """Fail loudly if the copied alphabet has drifted from the installed model's."""
    actual = torchaudio.pipelines.MMS_FA.get_dict()
    if actual != DICTIONARY:
        raise RuntimeError(f"MMS_FA alphabet changed: expected {DICTIONARY}, got {actual}")


def romanise(word: str) -> str:
    """One printed word reduced to the symbols the aligner knows.

    Diacritics are stripped rather than transliterated: the model was trained on romanised text
    of this shape, and `mulam` is what it expects to be shown for `mūlaṁ`. Hyphens go because
    '-' is the blank symbol and a target may never be blank. Digits and punctuation go because
    they are not sounds.

    The apostrophe is kept only inside a word. At an edge it is an avagraha marking an elided
    vowel (`prapanno 'smy`) or an English possessive - written, not spoken - and asking the
    aligner to find it would spend audio that belongs to the neighbouring letter.

    Curly and straight apostrophes are folded together first. This reference happens to use
    them consistently - U+2019 for all four avagrahas, U+0027 for all 122 contractions - but
    that is its habit, not a rule, and a source that writes `isn't` with a curly mark should
    not quietly lose the apostrophe the model expects to see.
    """
    plain = "".join(c for c in unicodedata.normalize("NFKD", word.replace("’", "'"))
                    if not unicodedata.combining(c))
    kept = "".join(c for c in plain.lower() if c in _ALIGNABLE)
    return kept.strip("'")


@dataclass
class Tokenised:
    """A word list flattened into targets, with the way back."""

    targets: list[int]
    owner: list[int]    # owner[i] is the index in the ORIGINAL word list that target i came from
    skipped: list[int]  # words with nothing alignable in them, by original index


def tokenise(words: list[str]) -> Tokenised:
    """Flatten words into CTC targets, remembering which word each target belongs to.

    `owner` is what makes the spans recoverable. Words that romanise to nothing - a verse
    number, a bare numeral - are recorded in `skipped` rather than dropped in silence, because
    a caller that believes it has one span per word will misread every span after the gap.
    """
    targets: list[int] = []
    owner: list[int] = []
    skipped: list[int] = []
    for index, word in enumerate(words):
        letters = romanise(word)
        if not letters:
            skipped.append(index)
            continue
        for character in letters:
            targets.append(DICTIONARY[character])
            owner.append(index)
    return Tokenised(targets, owner, skipped)


@dataclass
class WordSpan:
    """One word and when it was said. In frames until `to_seconds` is applied."""

    word: str
    index: int    # position in the transcript this word came from
    start: float
    end: float
    score: float  # mean acoustic probability over the word's frames, 0..1


def align(log_probs: torch.Tensor, words: list[str], blank: int = BLANK) -> list[WordSpan]:
    """Place each word in the frames where it was spoken.

    `log_probs` is (T, V) or (1, T, V) of log-probabilities over `DICTIONARY`. Spans come back
    in frames; `to_seconds` converts them once the model's frame rate is known.
    """
    flat = tokenise(words)
    if not flat.targets:
        return []

    batched = log_probs.unsqueeze(0) if log_probs.dim() == 2 else log_probs

    # CTC spends one frame per letter and one more on every doubled letter, for the blank that
    # keeps the pair apart. Below that the path does not exist. This is reachable in production
    # whenever a chunk is cut by time but filled by word count, and the error it otherwise
    # raises comes from C++ naming neither the chunk nor the text.
    repeats = sum(1 for a, b in zip(flat.targets, flat.targets[1:]) if a == b)
    needed = len(flat.targets) + repeats
    if batched.size(1) < needed:
        raise ValueError(
            f"{needed} frames needed to spell {len(words)} words "
            f"({len(flat.targets)} letters, {repeats} doubled), but only {batched.size(1)} given"
        )

    targets = torch.tensor([flat.targets], dtype=torch.int32)
    path, scores = torchaudio.functional.forced_align(batched, targets, blank=blank)
    token_spans = torchaudio.functional.merge_tokens(path[0], scores[0].exp(), blank=blank)

    # Forced alignment emits every target exactly once and in order, so any other count means
    # our own mapping is wrong rather than the audio being difficult. Say so, instead of
    # returning spans quietly attached to the wrong words.
    if len(token_spans) != len(flat.targets):
        raise RuntimeError(
            f"alignment returned {len(token_spans)} token spans for {len(flat.targets)} targets"
        )

    out: list[WordSpan] = []
    at = 0
    while at < len(flat.owner):
        index = flat.owner[at]
        end = at
        while end < len(flat.owner) and flat.owner[end] == index:
            end += 1
        group = token_spans[at:end]
        frames = sum(s.end - s.start for s in group) or 1
        out.append(WordSpan(
            word=words[index],
            index=index,
            start=group[0].start,
            end=group[-1].end,
            score=sum(s.score * (s.end - s.start) for s in group) / frames,
        ))
        at = end
    return out


def to_seconds(spans: list[WordSpan], seconds_per_frame: float,
               offset: float = 0.0) -> list[WordSpan]:
    """Frames to absolute seconds. `offset` is where this chunk began in the full recording."""
    return [replace(s, start=s.start * seconds_per_frame + offset,
                    end=s.end * seconds_per_frame + offset) for s in spans]


def stitch(chunks: list[tuple[list[WordSpan], int]]) -> list[WordSpan]:
    """Join per-chunk spans into one transcript-wide sequence.

    Each chunk aligned its own slice of the words and numbered them from zero, so `base` - where
    that slice began in the full transcript - is added back. Times are already absolute by this
    point, having been offset in `to_seconds`. Keeping the two corrections apart is what stops a
    chunk boundary from silently shifting either one.
    """
    out: list[WordSpan] = []
    for spans, base in chunks:
        out.extend(replace(s, index=s.index + base) for s in spans)
    return out


def read_window(path: str, start: float, end: float, pad: float = 0.0) -> torch.Tensor:
    """One window of a recording as 16 kHz mono, which is the only shape MMS_FA accepts.

    `pad` widens the window at both ends. Cue boundaries are where a human decided one caption
    should give way to the next, which is not the same as where the first word begins, so a
    little air on each side stops the aligner having to find a word that was cut in half.
    """
    with sf.SoundFile(path) as handle:
        rate = handle.samplerate
        first = max(0, int((start - pad) * rate))
        last = min(len(handle), int((end + pad) * rate))
        handle.seek(first)
        block = handle.read(last - first, dtype="float32", always_2d=True)
    mono = torch.from_numpy(block.mean(axis=1).astype(np.float32))
    if rate != SAMPLE_RATE:
        mono = torchaudio.functional.resample(mono, rate, SAMPLE_RATE)
    return mono


def check_model(log_probs: torch.Tensor) -> None:
    """Confirm the model still normalises the way `emissions` assumes it does.

    `get_model()` applies log-softmax over the 28 real symbols and then appends the star at
    probability 1, so `exp()` across all 29 sums to exactly 2, not 1. That is deliberate: a star
    is free to emit. It is also a trap, because the output looks like an unnormalised score and
    invites a log-softmax that must not be applied - see `emissions`.
    """
    total = log_probs.exp().sum(-1)
    if not torch.allclose(total, torch.full_like(total, 2.0), atol=1e-3):
        raise RuntimeError(
            f"MMS_FA normalisation changed: exp() sums to {total.mean():.4f}, expected 2.0 "
            "(28 symbols summing to 1, plus the star at probability 1)"
        )


@lru_cache(maxsize=1)
def acoustic_model():
    """MMS_FA, loaded once. 1.2 GB of weights is not something to pay for twice."""
    check_dictionary()
    model = torchaudio.pipelines.MMS_FA.get_model()
    model.eval()
    with torch.inference_mode():
        check_model(model(torch.zeros(1, SAMPLE_RATE))[0])
    return model


def emissions(waveform: torch.Tensor) -> tuple[torch.Tensor, float]:
    """Frame-level log-probabilities over the alphabet, and how long one frame lasts.

    The model's output is ALREADY log-probabilities and must not be softmaxed again. It arrives
    log-softmaxed over the 28 real symbols with the star appended at probability 1, so `exp()`
    sums to 2. Renormalising over all 29 subtracts log 2 from every symbol at every frame -
    which, being a uniform offset, leaves the Viterbi path and so every timestamp untouched,
    and quietly halves every confidence score. A timing bug announces itself; that one does not.

    The frame rate is derived from the model's own output length rather than assumed to be the
    nominal 50 Hz, because the convolutional front end drops a partial frame at the end and an
    assumed rate would accumulate that error across a long recording.
    """
    with torch.inference_mode():
        log_probs, _ = acoustic_model()(waveform.unsqueeze(0))
    seconds_per_frame = waveform.size(0) / log_probs.size(1) / SAMPLE_RATE
    return log_probs, seconds_per_frame


def align_window(path: str, start: float, end: float, words: list[str],
                 pad: float = 0.0) -> list[WordSpan]:
    """Word spans in absolute seconds for a stretch of a recording whose words are known.

    This is the whole pipeline for one segment: read the audio, score it, find the path that
    spells the words, and report when each was said.
    """
    waveform = read_window(path, start, end, pad)
    log_probs, seconds_per_frame = emissions(waveform)
    spans = align(log_probs, words)
    return to_seconds(spans, seconds_per_frame, offset=max(0.0, start - pad))


# Editorial annotations, the repository's existing convention for "written, not spoken".
_BRACKETED = re.compile(r"\[[^\]]*\]")


def spoken_words(text: str) -> list[str]:
    """The words of a transcript line that were actually said aloud.

    A verified transcript carries more than speech, and forced alignment has no way to decline
    a word: anything left in the text is found anyway, in audio belonging to the words on either
    side, which are then placed wrongly too. Two kinds of writing have to go.

    Speaker labels - "Gour Govinda Swami:" marks who is talking and nobody pronounces it. On
    the Melbourne reference 43 of 512 cues carry one.

    Editorial brackets - `[verse]`, `[?]`, `[Śrīmad Bhāgavatam 5.5.8]`, and the bracketed word
    an editor supplied to finish a sentence. Melbourne happens to have none of these, but the
    next lecture in the queue has 28 of them carrying 60 phantom words, so this is a trap that
    is simply waiting rather than one that has been avoided.

    Both rules are the repository's existing ones, so the text being aligned and the text being
    scored agree about what counts as speech.
    """
    from scripts.transcript_accuracy import strip_speaker_label
    return _BRACKETED.sub(" ", strip_speaker_label(text)).split()


@dataclass
class Chunk:
    """A window of audio to score, and the part of it worth keeping."""

    start: int      # first sample handed to the encoder
    end: int        # last sample handed to the encoder
    keep_from: int  # first sample whose frames survive
    keep_to: int    # last sample whose frames survive


def plan_chunks(samples: int, window: float = 30.0, overlap: float = 2.0) -> list[Chunk]:
    """How to score audio too long for one encoder pass, without moving anything.

    wav2vec2's attention is quadratic in frames, though the cost stays flat in practice out to
    about a minute and only then begins to tell (measured: 0.43-0.48x real time at 10, 30 and
    60 seconds, 0.61x at 120). Windows therefore overlap, and the frames nearest each seam -
    scored with only half the context they deserve - are thrown away in favour of the
    neighbour's, which saw them in the middle of its own window.

    The windows are spread evenly rather than laid on a fixed grid, so the last one ends exactly
    at the end of the audio and there is never a final sliver scored with no context. What each
    chunk keeps is cut at the midpoint of its overlap with the next, which makes the kept
    regions tile the recording exactly once: no gap, no repetition, nothing shifted.
    """
    if samples <= 0:
        return []
    width = int(window * SAMPLE_RATE)
    if samples <= width:
        return [Chunk(0, samples, 0, samples)]

    step = width - int(overlap * SAMPLE_RATE)
    count = -(-(samples - width) // step) + 1  # ceiling division, then the first window
    starts = [round(i * (samples - width) / (count - 1)) for i in range(count)]
    bounds = [(start, start + width) for start in starts]

    plan = []
    for index, (start, end) in enumerate(bounds):
        keep_from = start if index == 0 else (bounds[index][0] + bounds[index - 1][1]) // 2
        keep_to = end if index == count - 1 else (bounds[index + 1][0] + end) // 2
        plan.append(Chunk(start, end, keep_from, keep_to))
    return plan


def emissions_long(waveform: torch.Tensor, window: float = 30.0, overlap: float = 2.0,
                   score=None) -> tuple[torch.Tensor, float]:
    """Score audio of any length, one window at a time, and join the results.

    Each window is scored with context on both sides and then trimmed back to the part it was
    best placed to judge, so the surviving frames tile the recording exactly once. The frame
    duration is measured from the joined result rather than assumed, which keeps the arithmetic
    honest even though the windows do not divide the audio evenly.

    `score` exists so the joining can be tested without loading 1.2 GB of weights.
    """
    score = score or emissions
    plan = plan_chunks(waveform.size(0), window, overlap)
    if not plan:
        raise ValueError("no audio to score")

    kept = []
    for chunk in plan:
        log_probs, _ = score(waveform[chunk.start:chunk.end])
        frames = log_probs.size(1)
        width = chunk.end - chunk.start
        first = round((chunk.keep_from - chunk.start) / width * frames)
        last = round((chunk.keep_to - chunk.start) / width * frames)
        kept.append(log_probs[:, first:last])

    joined = torch.cat(kept, dim=1)
    return joined, waveform.size(0) / joined.size(1) / SAMPLE_RATE


def problems(spans: list[WordSpan], duration: float | None = None) -> list[str]:
    """Everything wrong with a finished alignment, in plain words.

    Read-along fails quietly. A word placed before the one before it, or past the end of the
    recording, produces a page that highlights the wrong line and no error anywhere. These are
    the invariants that must hold however the spans were produced - one long pass, cue by cue,
    or segment by segment with offsets added back - which is exactly why they are checked on the
    result rather than inside any one of those paths.
    """
    found = []
    backwards = sum(1 for a, b in zip(spans, spans[1:]) if b.start < a.start)
    if backwards:
        found.append(f"{backwards} words start before the word before them")
    inverted = sum(1 for s in spans if s.end < s.start)
    if inverted:
        found.append(f"{inverted} words end before they start")
    if any(s.start < 0 for s in spans):
        found.append(f"{sum(1 for s in spans if s.start < 0)} words start before the recording")
    if duration is not None:
        past = sum(1 for s in spans if s.end > duration + 0.5)
        if past:
            found.append(f"{past} words end after the recording does")
    return found
