"""Beat-grid quantization utilities."""

from __future__ import annotations

import numpy as np

from app.types import NoteEvent


def median_interval(beats: np.ndarray) -> float:
    if len(beats) >= 2:
        value = float(np.median(np.diff(beats)))
        if value > 0:
            return value
    return 0.5


class BeatGridQuantizer:
    """Map note times onto a beat grid.

    The grid may be irregular (Beat-This output); positions are interpolated
    between detected beats and extrapolated at the edges using the median
    beat interval.
    """

    def __init__(self, beats: list[float] | np.ndarray, subdivision: int = 4):
        beats = np.asarray(sorted(float(b) for b in beats), dtype=float)
        if len(beats) < 2:
            raise ValueError("At least two beats are required")
        self.beats = beats
        self.positions = np.arange(len(beats), dtype=float)
        self.interval = median_interval(beats)
        self.subdivision = max(1, int(subdivision))

    def time_to_position(self, t: float) -> float:
        if t <= self.beats[0]:
            return (t - self.beats[0]) / self.interval
        if t >= self.beats[-1]:
            return (len(self.beats) - 1) + (t - self.beats[-1]) / self.interval
        return float(np.interp(t, self.beats, self.positions))

    def position_to_time(self, position: float) -> float:
        if position <= self.positions[0]:
            return self.beats[0] + (position - self.positions[0]) * self.interval
        if position >= self.positions[-1]:
            return self.beats[-1] + (position - self.positions[-1]) * self.interval
        return float(np.interp(position, self.positions, self.beats))

    def quantize_position(self, position: float) -> float:
        return round(position * self.subdivision) / self.subdivision

    def quantize_notes(self, notes: list[NoteEvent]) -> list[NoteEvent]:
        step = 1.0 / self.subdivision
        quantized: list[NoteEvent] = []
        for note in notes:
            start_pos = self.quantize_position(self.time_to_position(note.start))
            end_pos = self.quantize_position(self.time_to_position(note.end))
            if end_pos <= start_pos:
                end_pos = start_pos + step
            start = max(0.0, self.position_to_time(start_pos))
            end = self.position_to_time(end_pos)
            if end <= start:
                end = start + step
            quantized.append(
                NoteEvent(
                    start=start,
                    end=end,
                    pitch=note.pitch,
                    velocity=note.velocity,
                    confidence=note.confidence,
                )
            )
        return quantized


def regular_beats(duration: float, bpm: float = 120.0) -> np.ndarray:
    interval = 60.0 / max(bpm, 1e-6)
    count = int(duration / interval) + 2
    return np.arange(count, dtype=float) * interval


def infer_time_signature(beats: list[float], downbeats: list[float]) -> tuple[str, float]:
    """Infer a time signature from beat/downbeat spacing."""
    if len(beats) < 4 or len(downbeats) < 2:
        return "4/4", 0.0

    counts: list[int] = []
    for start, end in zip(downbeats[:-1], downbeats[1:]):
        count = int(((np.asarray(beats) >= start) & (np.asarray(beats) < end)).sum())
        if count > 0:
            counts.append(count)
    if not counts:
        return "4/4", 0.0

    median = int(np.median(counts))
    mapping = {2: "2/4", 3: "3/4", 4: "4/4", 6: "6/8", 9: "9/8", 12: "12/8"}
    signature = mapping.get(median, "4/4")
    agreement = sum(1 for count in counts if count == median) / len(counts)
    return signature, float(agreement)
