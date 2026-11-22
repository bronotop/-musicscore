"""Spotify Basic Pitch adapter (Apache-2.0 code, ONNX or TensorFlow runtime).

Basic Pitch ships an ONNX model, so it works on Windows/Python 3.12 without
TensorFlow. The package still logs "Tensorflow is not installed" at import
time, which is harmless; suppress those import-time warnings.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.models.adapters.common import MissingDependencyError, NoteEvent, note_events_to_midi


def _load():
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.ERROR)
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict
    except ImportError as exc:
        raise MissingDependencyError(
            "Missing dependency 'basic_pitch'. Install with: "
            "pip install --no-deps basic-pitch"
        ) from exc
    finally:
        root.setLevel(previous)
    return ICASSP_2022_MODEL_PATH, predict


def transcribe(
    audio_path: Path,
    out_midi: Path,
    program: int = 0,
    min_frequency: float = 32.7,
    max_frequency: float = 2093.0,
    min_note_length_ms: float = 58.0,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    bpm: float = 120.0,
) -> tuple[list[NoteEvent], str]:
    model_path, predict = _load()

    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        _, _, events = predict(
            str(audio_path),
            model_path,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=min_note_length_ms,
            minimum_frequency=min_frequency,
            maximum_frequency=max_frequency,
            multiple_pitch_bends=False,
            melodia_trick=True,
        )

    notes: list[NoteEvent] = []
    for event in events:
        if len(event) >= 5:
            start, end, pitch, amplitude = event[0], event[1], event[2], event[3]
        elif len(event) == 4:
            start, end, pitch, amplitude = event
        else:
            continue
        amplitude = float(np.clip(amplitude, 0.0, 1.0))
        notes.append(
            NoteEvent(
                start=float(start),
                end=float(end),
                pitch=int(round(pitch)),
                velocity=int(np.clip(amplitude * 127.0, 1, 127)),
                confidence=amplitude,
            )
        )

    note_events_to_midi(notes, out_midi, program=program, bpm=bpm, name="basic-pitch")
    return notes, "basic-pitch"
