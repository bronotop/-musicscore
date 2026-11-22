"""Solo / single-instrument transcription driven by the instrument catalog."""

from __future__ import annotations

from pathlib import Path

from app.instruments import InstrumentProfile
from app.models.adapters import basic_pitch, drums, pitch, vocals
from app.models.adapters.common import note_events_to_midi
from app.services.fusion import FusionProfile, fuse_notes
from app.types import NoteEvent


def _hz(pitch: float) -> float:
    return 440.0 * 2.0 ** ((float(pitch) - 69.0) / 12.0)


def _range_hz(profile: InstrumentProfile) -> tuple[float, float]:
    low = max(32.7, _hz(max(0, profile.range_low)))
    high = max(low + 1.0, _hz(max(profile.range_low + 1, profile.range_high)))
    return low, high


def _filter_range(notes: list[NoteEvent], profile: InstrumentProfile) -> list[NoteEvent]:
    return [
        note
        for note in notes
        if profile.range_low <= note.pitch <= profile.range_high
    ]


def transcribe(
    audio_path: Path,
    out_midi: Path,
    profile: InstrumentProfile,
    bpm: float = 120.0,
    quality: bool = False,
) -> tuple[list[NoteEvent], str]:
    """Transcribe one isolated instrument according to its catalog profile."""
    if profile.notation == "none" or profile.family == "effect":
        return [], "skipped-fx"

    if profile.id in {"vocals", "voice"}:
        notes, model = vocals.transcribe(
            audio_path, out_midi, bpm=bpm, quality=quality
        )
        notes = _filter_range(notes, profile)
        note_events_to_midi(
            notes,
            out_midi,
            program=profile.gm_program,
            bpm=bpm,
            name=profile.id,
        )
        return notes, f"solo-{model}"

    if profile.notation == "percussion" or profile.family == "percussion":
        notes, model = drums.transcribe(audio_path, out_midi, bpm=bpm)
        note_events_to_midi(
            notes,
            out_midi,
            program=0,
            is_drum=True,
            bpm=bpm,
            name=profile.id,
        )
        return notes, f"solo-{model}"

    low, high = _range_hz(profile)
    if profile.monophonic:
        notes, model = pitch.transcribe(
            audio_path,
            out_midi,
            program=profile.gm_program,
            bpm=bpm,
            fmin=low,
            fmax=high,
        )
        notes = _filter_range(notes, profile)
    else:
        notes, model = basic_pitch.transcribe(
            audio_path,
            out_midi,
            program=profile.gm_program,
            min_frequency=low,
            max_frequency=high,
            min_note_length_ms=55.0 if quality else 58.0,
            onset_threshold=0.40 if quality else 0.45,
            frame_threshold=0.25 if quality else 0.30,
            bpm=bpm,
        )
        notes = _filter_range(notes, profile)
        fusion_profile = FusionProfile(
            min_confidence=0.25,
            min_duration=0.045,
            max_polyphony=max(1, profile.max_polyphony),
            density_limit=0.0,
            # Plucked/ethnic strings often produce octave harmonics in Basic
            # Pitch; merge them for a cleaner draft (policy favors confidence).
            octave_merge=profile.family in {"chinese", "ethnic", "plucked"},
            octave_policy="confidence",
        )
        notes, _ = fuse_notes(
            profile.id,
            notes,
            profile=fusion_profile,
            duration=None,
        )

    note_events_to_midi(
        notes,
        out_midi,
        program=profile.gm_program,
        bpm=bpm,
        name=profile.id,
    )
    return notes, f"solo-{model}"
