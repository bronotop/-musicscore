"""Shared helpers for model adapters."""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np

from app.types import NoteEvent


class MissingDependencyError(RuntimeError):
    pass


def require(module: str, hint: str = ""):
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        message = f"Missing dependency '{module}'."
        if hint:
            message += f" {hint}"
        raise MissingDependencyError(message) from exc


def resolve_device(preferred: str | None = "auto") -> str:
    if preferred and preferred != "auto":
        return preferred
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def empty_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def note_events_to_midi(
    notes: list[NoteEvent],
    out_path: Path,
    program: int = 0,
    is_drum: bool = False,
    bpm: float = 120.0,
    name: str = "",
) -> Path:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm))
    instrument = pretty_midi.Instrument(
        program=int(program), is_drum=bool(is_drum), name=name
    )
    for note in notes:
        if note.end <= note.start:
            continue
        instrument.notes.append(
            pretty_midi.Note(
                velocity=int(np.clip(note.velocity, 1, 127)),
                pitch=int(np.clip(note.pitch, 0, 127)),
                start=float(note.start),
                end=float(note.end),
            )
        )
    midi.instruments.append(instrument)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(out_path))
    return out_path


def count_midi_notes(path: Path) -> int:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(path))
    return sum(len(instrument.notes) for instrument in midi.instruments)


def _score(note: NoteEvent) -> float:
    return float(note.velocity) * max(float(note.confidence), 0.01)


def monophonic_filter(notes: list[NoteEvent], tolerance: float = 0.02) -> list[NoteEvent]:
    """Keep a single sounding line by resolving overlaps by score."""
    kept: list[NoteEvent] = []
    for note in sorted(notes, key=lambda item: (item.start, -_score(item))):
        if not kept:
            kept.append(note)
            continue
        previous = kept[-1]
        if note.start >= previous.end - tolerance:
            kept.append(note)
            continue
        if _score(note) > _score(previous):
            previous.end = max(previous.start + 0.01, note.start)
            if previous.end <= previous.start:
                kept.pop()
            kept.append(note)
        else:
            shifted_start = max(note.start, previous.end)
            if note.end > shifted_start:
                note.start = shifted_start
                kept.append(note)
    return kept
