"""Monophonic pitch-tracking fallback (torchcrepe, then librosa.pyin).

Used when Basic Pitch or MuScriptor are not installed. It produces a single
melody line, which is appropriate for vocals and bass and a rough sketch for
guitar. Polyphonic accuracy is intentionally out of scope here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.models.adapters.common import note_events_to_midi, resolve_device
from app.types import NoteEvent

ANALYSIS_SR = 16000
HOP = 160  # 10 ms


def _track_f0(
    audio_path: Path, fmin: float, fmax: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    import librosa

    y, sr = librosa.load(str(audio_path), sr=ANALYSIS_SR, mono=True)
    if y.size == 0:
        return (
            np.array([]),
            np.array([]),
            np.array([], dtype=bool),
            np.array([]),
        )

    try:
        import torch
        import torchcrepe

        # torchcrepe rejects fmin below its 32.7 Hz model floor and returns
        # all-zero pitch instead of raising.
        crepe_fmin = max(32.7, float(fmin))
        device = resolve_device("auto")
        tensor = torch.from_numpy(y)[None, :].to(device)
        pitch, periodicity = torchcrepe.predict(
            tensor,
            ANALYSIS_SR,
            hop_length=HOP,
            fmin=crepe_fmin,
            fmax=fmax,
            model="full",
            batch_size=1024,
            device=device,
            return_periodicity=True,
        )
        f0 = pitch[0].detach().cpu().numpy()
        confidence = periodicity[0].detach().cpu().numpy()
        times = np.arange(len(f0), dtype=float) * HOP / ANALYSIS_SR
        voiced = (f0 > 0) & (confidence > 0.30)
        return times, f0, voiced, confidence
    except Exception:
        frame_length = 4096 if fmin < 65 else 2048
        f0, voiced, _ = librosa.pyin(
            y,
            fmin=fmin,
            fmax=fmax,
            sr=ANALYSIS_SR,
            frame_length=frame_length,
            hop_length=HOP,
        )
        times = librosa.times_like(f0, sr=ANALYSIS_SR, hop_length=HOP)
        voiced = np.isfinite(f0) & (f0 > 0)
        f0 = np.nan_to_num(f0, nan=0.0)
        # pyin returns a voiced flag but no probability; use a fixed moderate
        # confidence so these notes are visibly less certain than model output.
        confidence = np.where(voiced, 0.55, 0.0)
        return times, f0, voiced, confidence


def _segment_notes(
    times: np.ndarray,
    f0: np.ndarray,
    voiced: np.ndarray,
    confidence: np.ndarray | None = None,
    min_duration: float = 0.06,
    max_gap: float = 0.04,
    pitch_tolerance: float = 0.8,
) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    if len(times) == 0:
        return notes
    if confidence is None or len(confidence) != len(times):
        confidence = np.where(voiced, 0.5, 0.0)

    current_start: float | None = None
    current_pitches: list[float] = []
    current_confidences: list[float] = []
    last_voiced_time: float | None = None

    def close(end_time: float) -> None:
        nonlocal current_start, current_pitches, current_confidences, last_voiced_time
        if current_start is not None and current_pitches:
            duration = end_time - current_start
            if duration >= min_duration:
                pitch = int(round(float(np.median(current_pitches))))
                note_confidence = float(np.median(current_confidences))
                notes.append(
                    NoteEvent(
                        start=float(current_start),
                        end=float(end_time),
                        pitch=max(0, min(127, pitch)),
                        velocity=88,
                        confidence=max(0.05, min(1.0, note_confidence)),
                    )
                )
        current_start = None
        current_pitches = []
        current_confidences = []
        last_voiced_time = None

    for time, frequency, is_voiced, frame_confidence in zip(
        times, f0, voiced, confidence
    ):
        if not is_voiced or frequency <= 0:
            if current_start is not None and last_voiced_time is not None and time - last_voiced_time > max_gap:
                close(last_voiced_time + max_gap)
            continue

        midi = 69.0 + 12.0 * np.log2(frequency / 440.0)
        if current_start is None:
            current_start = float(time)
            current_pitches = [midi]
            current_confidences = [float(frame_confidence)]
        elif abs(midi - float(np.median(current_pitches))) <= pitch_tolerance:
            current_pitches.append(midi)
            current_confidences.append(float(frame_confidence))
        else:
            close(float(time))
            current_start = float(time)
            current_pitches = [midi]
            current_confidences = [float(frame_confidence)]
        last_voiced_time = float(time)

    if current_start is not None:
        close(float(times[-1]) + HOP / ANALYSIS_SR)
    return notes


def transcribe(
    audio_path: Path,
    out_midi: Path,
    program: int = 53,
    bpm: float = 120.0,
    fmin: float = 65.0,
    fmax: float = 1200.0,
    is_drum: bool = False,
) -> tuple[list[NoteEvent], str]:
    times, f0, voiced, confidence = _track_f0(audio_path, fmin=fmin, fmax=fmax)
    notes = _segment_notes(times, f0, voiced, confidence)
    note_events_to_midi(
        notes,
        out_midi,
        program=program,
        is_drum=is_drum,
        bpm=bpm,
        name="pitch-fallback",
    )
    return notes, "pitch-fallback"
