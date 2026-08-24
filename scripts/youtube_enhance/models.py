from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SegmentLabel(str, Enum):
    MAIN_SPEECH = "main_speech"
    MIXED_OR_AUDIENCE_SPEECH = "mixed_or_audience_speech"
    CHANTING_OR_MUSIC = "chanting_or_music"
    APPLAUSE_OR_CROWD = "applause_or_crowd"
    GUARDED_PAUSE = "guarded_pause"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Segment:
    start_sample: int
    end_sample: int
    label: SegmentLabel
    reviewed: bool
    notes: str = ""


@dataclass(frozen=True)
class Core:
    start_sample: int
    end_sample: int


@dataclass(frozen=True)
class Approval:
    blind_code: str
    candidate_id: str
    pause_treatment: str
    reviewer: str
    approved_at: str
    fingerprint: str
