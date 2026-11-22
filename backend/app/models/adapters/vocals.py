"""Vocal melody transcription.

Preferred path: GAME (MIT, ONNX) for singing-voice notes.  If GAME is not
installed, fails, or produces a suspiciously sparse result for the stem, the
adapter falls back to Basic Pitch plus melody-line selection driven by a
torchcrepe/pyin pitch track.  ``VOCAL_MELODY_MODE`` selects the strategy:

    auto (default)  GAME when available and plausible, otherwise heuristic
    game            force GAME (still falls back if the model is missing)
    heuristic       skip GAME; Basic Pitch + melody-line selection
    basic           old behaviour: Basic Pitch + monophonic_filter
"""

from __future__ import annotations

import os
from pathlib import Path

from app.models.adapters import basic_pitch, game, melody, pitch
from app.models.adapters.common import monophonic_filter, note_events_to_midi
from app.types import NoteEvent


def _mode() -> str:
    value = os.environ.get("VOCAL_MELODY_MODE", "auto").strip().lower()
    if value in {"auto", "game", "heuristic", "basic"}:
        return value
    return "auto"


def _basic_pitch(
    audio_path: Path,
    out_midi: Path,
    bpm: float,
    min_frequency: float,
    max_frequency: float,
    quality: bool = False,
) -> tuple[list[NoteEvent], str]:
    try:
        return basic_pitch.transcribe(
            audio_path,
            out_midi,
            program=53,
            min_frequency=min_frequency,
            max_frequency=max_frequency,
            min_note_length_ms=60.0 if quality else 70.0,
            onset_threshold=0.40 if quality else 0.45,
            frame_threshold=0.25 if quality else 0.30,
            bpm=bpm,
        )
    except Exception:
        return pitch.transcribe(
            audio_path,
            out_midi,
            program=53,
            bpm=bpm,
            fmin=min_frequency,
            fmax=max_frequency,
        )


def _active_seconds(notes: list[NoteEvent]) -> float:
    return sum(max(0.0, note.end - note.start) for note in notes)


def _game_is_dense(notes: list[NoteEvent], duration: float) -> bool:
    """Quick check whether GAME found a plausible melody without a reference."""
    if len(notes) < 4:
        return False
    if duration <= 0.0:
        return True
    if _active_seconds(notes) < 0.20 * duration:
        return False
    # On quiet/bleed-heavy stems GAME can collapse to a handful of long
    # regions while covering enough time to pass a coverage-only check.
    return len(notes) / duration >= 0.45


def _game_matches_reference(
    notes: list[NoteEvent],
    reference: list[NoteEvent],
) -> bool:
    """Compare a sparse GAME result with Basic Pitch on the same stem.

    A synthetic/quiet stem can make GAME collapse to a few long regions while
    Basic Pitch still finds the melody.  In that case the heuristic path is a
    better draft.  On clean singing GAME's note count and coverage are close to
    (or better than) Basic Pitch.
    """
    if not notes:
        return False
    if not reference:
        return True
    if len(notes) < 0.45 * len(reference):
        return False
    reference_active = _active_seconds(reference)
    if reference_active > 0.0:
        if _active_seconds(notes) < 0.45 * reference_active:
            return False
    return True


def _finish(
    notes: list[NoteEvent],
    model: str,
    out_midi: Path,
    bpm: float,
) -> tuple[list[NoteEvent], str]:
    note_events_to_midi(notes, out_midi, program=53, bpm=bpm, name="vocals")
    return notes, model


def transcribe(
    audio_path: Path,
    out_midi: Path,
    bpm: float = 120.0,
    min_frequency: float = 80.0,
    max_frequency: float = 1200.0,
    quality: bool = False,
) -> tuple[list[NoteEvent], str]:
    mode = _mode()
    config = melody.MelodyConfig.from_env()
    duration = melody.audio_duration(audio_path)

    if config.silence_rms > 0.0:
        rms = melody.audio_rms(audio_path)
        if rms is not None and rms < config.silence_rms:
            note_events_to_midi([], out_midi, program=53, bpm=bpm, name="vocals")
            return [], "silence-gate"

    reference_notes: list[NoteEvent] | None = None
    reference_model = ""
    game_notes: list[NoteEvent] | None = None
    game_model = ""
    game_attempted = False
    game_error = ""

    if mode in {"auto", "game"}:
        game_attempted = game.locate_model() is not None
        if game_attempted:
            try:
                game_notes, game_model = game.transcribe(
                    audio_path,
                    out_midi,
                    bpm=bpm,
                    min_frequency=min_frequency,
                    max_frequency=max_frequency,
                    quality=quality,
                )
            except Exception as exc:
                game_error = f"{type(exc).__name__}: {exc}"
                game_notes = None

            if game_notes is not None:
                cleaned_game = melody.select_melody(game_notes, track=None, config=config)
                if mode == "game":
                    if cleaned_game:
                        return _finish(
                            cleaned_game,
                            f"{game_model}+melody",
                            out_midi,
                            bpm,
                        )
                elif _game_is_dense(cleaned_game, duration):
                    # Gate on the cleaned line, not the raw model regions:
                    # short/fragment regions can look dense before cleanup.
                    if cleaned_game:
                        return _finish(
                            cleaned_game,
                            f"{game_model}+melody",
                            out_midi,
                            bpm,
                        )
                else:
                    # Sparse GAME result: ask Basic Pitch whether the stem has
                    # a richer melody.  The notes are reused if we fall back.
                    reference_notes, reference_model = _basic_pitch(
                        audio_path,
                        out_midi,
                        bpm,
                        min_frequency,
                        max_frequency,
                        quality=quality,
                    )
                    if _game_matches_reference(cleaned_game, reference_notes):
                        if cleaned_game:
                            return _finish(
                                cleaned_game,
                                f"{game_model}+melody",
                                out_midi,
                                bpm,
                            )
            elif mode == "game":
                # Force mode still needs a usable result; fall through to the
                # heuristic rather than returning an empty vocal track.
                pass

    if reference_notes is None:
        reference_notes, reference_model = _basic_pitch(
            audio_path,
            out_midi,
            bpm,
            min_frequency,
            max_frequency,
            quality=quality,
        )

    if mode == "basic":
        cleaned = monophonic_filter(reference_notes)
        return _finish(cleaned, f"{reference_model}+mono", out_midi, bpm)

    track = None
    if config.use_pitch_track:
        track = melody.track_f0(
            audio_path,
            fmin=min_frequency,
            fmax=max_frequency,
        )
    cleaned = melody.select_melody(reference_notes, track=track, config=config)
    if not cleaned:
        cleaned = monophonic_filter(reference_notes)

    suffix = "melody" if track is not None else "melody-no-f0"
    prefix = ""
    if game_notes is not None:
        prefix = "game-sparse->"
    elif game_error:
        prefix = "game-failed->"
    elif mode == "game":
        prefix = "game-unavailable->"
    return _finish(cleaned, f"{prefix}{reference_model}+{suffix}", out_midi, bpm)
