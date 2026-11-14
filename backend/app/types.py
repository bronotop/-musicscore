"""Shared data types used across the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

STEMS: tuple[str, ...] = ("vocals", "drums", "bass", "guitar", "piano", "other")

# General MIDI programs used when writing the merged multi-track MIDI.
INSTRUMENT_PROGRAMS: dict[str, int] = {
    "vocals": 53,   # Voice Oohs
    "piano": 0,     # Acoustic Grand Piano
    "guitar": 25,   # Acoustic Guitar (steel)
    "bass": 33,     # Electric Bass (finger)
    "other": 48,    # String Ensemble 1
}

# ADTOF's five output classes mapped onto General MIDI percussion notes.
DRUM_GM_MAP: dict[str, int] = {
    "kick": 36,
    "snare": 38,
    "closed_hat": 42,
    "open_hat": 46,
    "tom": 45,
    "crash": 49,
    "ride": 51,
}


@dataclass
class AudioInfo:
    path: str
    sample_rate: int
    channels: int
    duration: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NoteEvent:
    start: float
    end: float
    pitch: int
    velocity: int = 80
    confidence: float = 1.0


@dataclass
class BeatGrid:
    bpm: float
    beats: list[float]
    downbeats: list[float] = field(default_factory=list)
    time_signature: str = "4/4"
    key: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrackInfo:
    name: str
    instrument: str
    midi_path: str
    note_count: int
    model: str
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def relpath(path: Path, root: Path) -> str:
    """Return a POSIX-style path relative to *root* for manifests."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
