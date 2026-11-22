"""General / guitar / other transcription.

MuScriptor (code MIT, weights CC BY-NC 4.0) is preferred when local weights
are present. Basic Pitch is the polyphonic fallback, and monophonic pitch
tracking is the last resort so the pipeline always completes.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.models.adapters import basic_pitch, muscriptor, pitch
from app.models.adapters.common import note_events_to_midi
from app.types import NoteEvent

GUITAR_INSTRUMENTS = [
    "acoustic_guitar",
    "clean_electric_guitar",
    "distorted_electric_guitar",
]
GUITAR_RANGE = (40, 88)  # E2..E6, filters bleed from drums/bass/woodwinds


def _muscriptor_instruments(instrument_hint: str | None) -> list[str] | None:
    if instrument_hint == "guitar":
        return GUITAR_INSTRUMENTS
    return None


def _filter_range(notes: list[NoteEvent], low: int, high: int) -> list[NoteEvent]:
    return [note for note in notes if low <= note.pitch <= high]


def transcribe(
    audio_path: Path,
    out_midi: Path,
    program: int = 48,
    bpm: float = 120.0,
    min_frequency: float = 60.0,
    max_frequency: float = 2000.0,
    model: str = "auto",
    device: str = "auto",
    instrument_hint: str | None = None,
    quality: bool = False,
) -> tuple[list[NoteEvent], str]:
    use_muscriptor = model == "muscriptor" or (
        model == "auto" and os.environ.get("MUSCRIPTOR_STEM_MODE") == "1"
    )
    if use_muscriptor:
        try:
            if instrument_hint == "guitar":
                notes, label = muscriptor.transcribe(
                    audio_path,
                    out_midi,
                    instruments=GUITAR_INSTRUMENTS,
                    quality=quality,
                )
                if not notes:
                    # A separated guitar stem often does not match the model's
                    # guitar classes; fall back to unconstrained output and
                    # keep only the guitar register.
                    notes, label = muscriptor.transcribe(
                        audio_path,
                        out_midi,
                        instruments=None,
                        quality=quality,
                    )
                    notes = _filter_range(notes, *GUITAR_RANGE)
                    if notes:
                        note_events_to_midi(
                            notes,
                            out_midi,
                            program=program,
                            bpm=bpm,
                            name="guitar",
                        )
                        label = f"{label}+range"
                if not notes:
                    raise RuntimeError("MuScriptor returned no guitar notes")
                return notes, label

            notes, label = muscriptor.transcribe(
                audio_path, out_midi, instruments=None, quality=quality
            )
            if instrument_hint == "other" and len(notes) < 10:
                print(f"      MuScriptor returned only {len(notes)} notes; using fallback")
            else:
                return notes, label
        except Exception as exc:
            if model == "muscriptor":
                raise
            print(f"      MuScriptor unavailable ({type(exc).__name__}: {exc}); using fallback")

    try:
        return basic_pitch.transcribe(
            audio_path,
            out_midi,
            program=program,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            min_note_length_ms=55.0 if quality else 58.0,
            onset_threshold=0.42 if quality else 0.5,
            frame_threshold=0.28 if quality else 0.3,
            bpm=bpm,
        )
    except Exception:
        if model == "basic-pitch":
            raise
        return pitch.transcribe(
            audio_path,
            out_midi,
            program=program,
            bpm=bpm,
            fmin=min_frequency,
            fmax=min(max_frequency, 2000.0),
        )
