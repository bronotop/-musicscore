"""Melody-line selection and monophonic cleanup for vocal stems.

The heuristic path starts from a polyphonic transcription (Basic Pitch) plus a
monophonic f0 track (torchcrepe, then librosa.pyin).  Vocal stems often contain
accompaniment bleed and octave/fifth harmonics of the sung note; Basic Pitch
reports both.  This module keeps the note that agrees with the f0 track,
resolves remaining overlaps by confidence/velocity, merges vibrato fragments,
and enforces a single sounding line.

All thresholds can be overridden through ``VOCAL_MELODY_*`` environment
variables; see :class:`MelodyConfig`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from app.types import NoteEvent

ANALYSIS_SR = 16000
HOP = 160


@dataclass
class PitchTrack:
    """Frame-wise monophonic pitch track in MIDI semitones."""

    times: np.ndarray
    midi: np.ndarray
    confidence: np.ndarray


@dataclass(frozen=True)
class MelodyConfig:
    min_note_ms: float = 80.0
    min_confidence: float = 0.22
    pitch_tolerance: float = 1.5
    f0_confidence: float = 0.25
    merge_gap_ms: float = 60.0
    merge_pitch: float = 0.6
    max_leap: int = 12
    max_leap_note_ms: float = 120.0
    min_gap_ms: float = 25.0
    silence_rms: float = 0.0
    use_pitch_track: bool = True

    @classmethod
    def from_env(cls) -> "MelodyConfig":
        def number(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, default))
            except (TypeError, ValueError):
                return default

        use_f0 = os.environ.get("VOCAL_MELODY_USE_F0", "1").strip().lower()
        return cls(
            min_note_ms=max(10.0, number("VOCAL_MELODY_MIN_NOTE_MS", 80.0)),
            min_confidence=min(1.0, max(0.0, number("VOCAL_MELODY_MIN_CONFIDENCE", 0.22))),
            pitch_tolerance=max(0.0, number("VOCAL_MELODY_PITCH_TOLERANCE", 1.5)),
            f0_confidence=min(1.0, max(0.0, number("VOCAL_MELODY_F0_CONFIDENCE", 0.25))),
            merge_gap_ms=max(0.0, number("VOCAL_MELODY_GAP_MS", 60.0)),
            merge_pitch=max(0.0, number("VOCAL_MELODY_MERGE_PITCH", 0.6)),
            max_leap=max(1, int(number("VOCAL_MELODY_MAX_LEAP", 12))),
            max_leap_note_ms=max(10.0, number("VOCAL_MELODY_MAX_LEAP_NOTE_MS", 120.0)),
            min_gap_ms=max(0.0, number("VOCAL_MELODY_MIN_GAP_MS", 25.0)),
            silence_rms=max(0.0, number("VOCAL_MELODY_SILENCE_RMS", 0.0)),
            use_pitch_track=use_f0 not in {"0", "false", "no", "off"},
        )


def _hz_to_midi(frequency):
    values = np.asarray(frequency, dtype=float)
    return 69.0 + 12.0 * np.log2(np.maximum(values, 1e-9) / 440.0)


def audio_duration(audio_path) -> float:
    """Return audio duration in seconds, or 0.0 when it cannot be read."""
    path = str(audio_path)
    try:
        import soundfile as sf

        info = sf.info(path)
        if info.samplerate:
            return float(info.frames) / float(info.samplerate)
    except Exception:
        pass
    try:
        import librosa

        return float(librosa.get_duration(path=path))
    except Exception:
        return 0.0


def audio_rms(audio_path) -> float | None:
    """Return the stem's RMS amplitude, or None when it cannot be read."""
    path = str(audio_path)
    try:
        import soundfile as sf

        data, _ = sf.read(path, dtype="float32", always_2d=True)
        if data.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.asarray(data, dtype=np.float64) ** 2)))
    except Exception:
        pass
    try:
        import librosa

        samples, _ = librosa.load(path, sr=None, mono=True)
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))
    except Exception:
        return None


def track_f0(
    audio_path,
    fmin: float = 65.0,
    fmax: float = 1200.0,
) -> PitchTrack | None:
    """Estimate a monophonic f0 track, normalising quiet stems first.

    torchcrepe is preferred (GPU when available); librosa.pyin is the fallback.
    Returns ``None`` when neither backend can produce a track.
    """
    try:
        import librosa

        y, _ = librosa.load(str(audio_path), sr=ANALYSIS_SR, mono=True)
    except Exception:
        return None
    if y.size == 0:
        return None
    y = np.asarray(y, dtype=np.float32)
    y = y - float(np.mean(y))
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak < 1e-6:
        return None
    y = (y / peak * 0.9).astype(np.float32)

    try:
        import torch
        import torchcrepe

        device = "cuda" if torch.cuda.is_available() else "cpu"
        with torch.no_grad():
            tensor = torch.from_numpy(y)[None, :].to(device)
            pitch, periodicity = torchcrepe.predict(
                tensor,
                ANALYSIS_SR,
                hop_length=HOP,
                fmin=max(32.7, float(fmin)),
                fmax=float(fmax),
                model="full",
                batch_size=1024,
                device=device,
                return_periodicity=True,
            )
        f0 = pitch[0].detach().cpu().numpy()
        confidence = periodicity[0].detach().cpu().numpy()
        times = np.arange(len(f0), dtype=float) * HOP / ANALYSIS_SR
        midi = np.where(
            f0 > 0,
            _hz_to_midi(f0),
            np.nan,
        )
        return PitchTrack(times=times, midi=midi, confidence=confidence)
    except Exception:
        pass

    try:
        import librosa

        frame_length = 4096 if fmin < 65 else 2048
        f0, voiced, _ = librosa.pyin(
            y,
            fmin=float(fmin),
            fmax=float(fmax),
            sr=ANALYSIS_SR,
            frame_length=frame_length,
            hop_length=HOP,
        )
        times = librosa.times_like(f0, sr=ANALYSIS_SR, hop_length=HOP)
        midi = np.where(np.isfinite(f0) & (f0 > 0), _hz_to_midi(np.nan_to_num(f0)), np.nan)
        confidence = np.where(np.isfinite(f0) & (f0 > 0), 0.55, 0.0)
        return PitchTrack(times=times, midi=midi, confidence=confidence)
    except Exception:
        return None


def _note_f0(
    track: PitchTrack | None,
    note: NoteEvent,
    f0_confidence: float,
) -> tuple[float | None, float]:
    if track is None:
        return None, 0.0
    mask = (track.times >= note.start) & (track.times < note.end)
    if not mask.any():
        return None, 0.0
    midi = track.midi[mask]
    confidence = track.confidence[mask]
    valid = np.isfinite(midi) & (confidence >= f0_confidence)
    if int(valid.sum()) < 2:
        return None, 0.0
    return float(np.median(midi[valid])), float(np.median(confidence[valid]))


def _score(note: NoteEvent) -> float:
    duration = max(float(note.end) - float(note.start), 0.01)
    return float(note.confidence) * float(note.velocity) * duration**0.3


def _copy_note(note: NoteEvent) -> NoteEvent:
    return NoteEvent(
        start=float(note.start),
        end=float(note.end),
        pitch=int(note.pitch),
        velocity=int(note.velocity),
        confidence=float(note.confidence),
    )


def select_melody(
    notes: list[NoteEvent],
    track: PitchTrack | None = None,
    config: MelodyConfig | None = None,
) -> list[NoteEvent]:
    """Select one melody line from polyphonic vocal-stem candidates.

    Steps:
      1. drop higher notes that are harmonic duplicates of a simultaneous
         lower note which matches the f0 track better;
      2. drop notes that disagree with the f0 track, are too short, or have
         low confidence;
      3. resolve overlaps by confidence * velocity * duration;
      4. merge same-pitch fragments (vibrato, split notes);
      5. drop isolated short fragments and implausible short leaps;
      6. leave a tiny gap between notes so strict monophony metrics agree.

    The input is not mutated.
    """
    cfg = config or MelodyConfig.from_env()
    work = [
        _copy_note(note)
        for note in notes
        if note.end > note.start and 0 <= int(note.pitch) <= 127
    ]
    if not work:
        return []
    work.sort(key=lambda item: (item.start, item.end, item.pitch))

    f0_info = {
        id(note): _note_f0(track, note, cfg.f0_confidence)
        for note in work
    }

    # 1. Remove obvious harmonics: a higher note overlapping a lower note that
    #    is closer to the f0 track is almost certainly an overtone.
    keep = [True] * len(work)
    if track is not None:
        for i, higher in enumerate(work):
            if not keep[i]:
                continue
            higher_f0, higher_conf = f0_info[id(higher)]
            if higher_f0 is None or higher_conf < cfg.f0_confidence:
                continue
            for j, lower in enumerate(work):
                if i == j or not keep[j] or lower.pitch >= higher.pitch:
                    continue
                overlap = min(higher.end, lower.end) - max(higher.start, lower.start)
                if overlap <= 0.01:
                    continue
                lower_f0, lower_conf = f0_info[id(lower)]
                if lower_f0 is None or lower_conf < cfg.f0_confidence:
                    continue
                if abs(lower_f0 - lower.pitch) + 0.5 < abs(higher_f0 - higher.pitch):
                    keep[i] = False
                    break

    # 2. Basic filtering and pitch agreement.
    filtered: list[NoteEvent] = []
    min_duration = cfg.min_note_ms / 1000.0
    for i, note in enumerate(work):
        if not keep[i]:
            continue
        if note.end - note.start < min_duration:
            continue
        if note.confidence < cfg.min_confidence:
            continue
        note_f0, f0_conf = f0_info[id(note)]
        if (
            track is not None
            and note_f0 is not None
            and f0_conf >= cfg.f0_confidence
            and abs(note.pitch - note_f0) > cfg.pitch_tolerance
        ):
            continue
        filtered.append(note)

    # 3. Score-aware monophonic sweep.
    monophonic: list[NoteEvent] = []
    for note in sorted(
        filtered,
        key=lambda item: (item.start, -_score(item)),
    ):
        if not monophonic:
            monophonic.append(note)
            continue
        previous = monophonic[-1]
        if note.start >= previous.end - 0.02:
            monophonic.append(note)
            continue
        previous_duration = previous.end - previous.start
        if _score(note) > _score(previous):
            previous.end = max(previous.start + 0.02, note.start)
            remaining = previous.end - previous.start
            if remaining < max(min_duration, 0.5 * previous_duration):
                monophonic.pop()
            monophonic.append(note)
        else:
            shifted_start = max(note.start, previous.end)
            if note.end - shifted_start >= 0.03:
                note.start = shifted_start
                monophonic.append(note)

    # 4. Merge same-pitch fragments and short gaps (vibrato/split notes).
    merged: list[NoteEvent] = []
    merge_gap = cfg.merge_gap_ms / 1000.0
    for note in monophonic:
        if merged:
            previous = merged[-1]
            gap = note.start - previous.end
            if (
                abs(note.pitch - previous.pitch) <= cfg.merge_pitch
                and gap <= merge_gap
            ):
                previous.end = max(previous.end, note.end)
                previous.confidence = max(previous.confidence, note.confidence)
                previous.velocity = max(previous.velocity, note.velocity)
                continue
        merged.append(note)

    # 5. Drop short notes and isolated implausible leaps.
    final: list[NoteEvent] = []
    max_leap_duration = cfg.max_leap_note_ms / 1000.0
    for note in merged:
        if note.end - note.start < min_duration:
            continue
        if final:
            previous = final[-1]
            if (
                abs(note.pitch - previous.pitch) > cfg.max_leap
                and note.end - note.start < max_leap_duration
            ):
                continue
        final.append(note)

    # 6. A 20 ms tolerance is used by the quality report; a 25 ms gap keeps
    #    adjacent notes from being counted as a chord.
    gap = cfg.min_gap_ms / 1000.0
    if gap > 0:
        for previous, note in zip(final, final[1:]):
            latest_end = note.start - gap
            if latest_end < previous.end:
                previous.end = max(previous.start + 0.03, latest_end)
        final = [note for note in final if note.end - note.start >= 0.03]

    final.sort(key=lambda item: (item.start, item.end, item.pitch))
    return final
