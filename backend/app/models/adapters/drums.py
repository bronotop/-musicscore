"""Drum transcription.

Preferred: ADTOF-pytorch (CC BY-NC-SA 4.0) with bundled 3.6 MB weights.
Fallbacks: the original ADTOF inference script if vendored, then a crude
onset + spectral-centroid transcriber so the pipeline always completes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from app.config import SETTINGS
from app.models.adapters.common import note_events_to_midi, resolve_device
from app.types import NoteEvent


def transcribe(
    audio_path: Path,
    out_midi: Path,
    bpm: float = 120.0,
) -> tuple[list[NoteEvent], str]:
    try:
        return _transcribe_adtof_pytorch(audio_path, out_midi, bpm)
    except Exception as exc:
        print(f"      ADTOF-pytorch unavailable ({type(exc).__name__}: {exc})")

    try:
        return _transcribe_adtof(audio_path, out_midi, bpm)
    except Exception:
        return _transcribe_onsets(audio_path, out_midi, bpm)


def _adtof_weights() -> Path:
    explicit = os.environ.get("ADTOF_WEIGHTS")
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists():
            return candidate
    vendored = (
        SETTINGS.home
        / "vendor"
        / "ADTOF-pytorch"
        / "data"
        / "adtof_frame_rnn_pytorch_weights.pth"
    )
    if vendored.exists():
        return vendored
    from adtof_pytorch import get_default_weights_path

    default = get_default_weights_path()
    if default and Path(default).exists():
        return Path(default)
    raise FileNotFoundError(
        "ADTOF-pytorch weights not found. Clone "
        "https://github.com/xavriley/ADTOF-pytorch into "
        f"{SETTINGS.home / 'vendor'} or set ADTOF_WEIGHTS."
    )


def _read_notes(path: Path) -> list[NoteEvent]:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(path))
    return [
        NoteEvent(n.start, n.end, n.pitch, n.velocity, 1.0)
        for instrument in midi.instruments
        for n in instrument.notes
    ]


def _transcribe_adtof_pytorch(
    audio_path: Path,
    out_midi: Path,
    bpm: float,
) -> tuple[list[NoteEvent], str]:
    from adtof_pytorch import transcribe_to_midi

    weights = _adtof_weights()
    options: dict = {}
    thresholds = os.environ.get("ADTOF_THRESHOLDS")
    if thresholds:
        values = [part.strip() for part in thresholds.split(",") if part.strip()]
        if values:
            options["thresholds"] = [float(value) for value in values]
    elif os.environ.get("ADTOF_THRESHOLD"):
        options["threshold"] = float(os.environ["ADTOF_THRESHOLD"])
    if os.environ.get("ADTOF_FPS"):
        options["fps"] = int(os.environ["ADTOF_FPS"])
    transcribe_to_midi(
        str(audio_path),
        str(out_midi),
        weights=str(weights),
        device=resolve_device("auto"),
        **options,
    )
    notes = _read_notes(out_midi)
    return notes, "adtof-pytorch"


def _transcribe_adtof(audio_path: Path, out_midi: Path, bpm: float):
    """Call a vendored original ADTOF inference script if present."""
    script = SETTINGS.home / "vendor" / "adtof" / "infer.py"
    if not script.exists():
        raise FileNotFoundError("ADTOF is not vendored")

    result = subprocess.run(
        [sys.executable, str(script), str(audio_path), str(out_midi)],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0 or not Path(out_midi).exists():
        raise RuntimeError(f"ADTOF failed: {result.stderr.strip()[-800:]}")

    return _read_notes(out_midi), "adtof"


def _transcribe_onsets(
    audio_path: Path,
    out_midi: Path,
    bpm: float,
) -> tuple[list[NoteEvent], str]:
    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    if y.size == 0:
        note_events_to_midi([], out_midi, is_drum=True, bpm=bpm, name="drums")
        return [], "drums-onset-fallback"

    onset_frames = librosa.onset.onset_detect(
        y=y,
        sr=sr,
        units="frames",
        backtrack=True,
    )
    times = librosa.frames_to_time(onset_frames, sr=sr)

    notes: list[NoteEvent] = []
    for time in times:
        start = max(0, int(time * sr))
        end = min(len(y), start + int(0.06 * sr))
        segment = y[start:end]
        if segment.size < 64:
            continue
        spectrum = np.abs(librosa.stft(segment, n_fft=1024))
        weights = spectrum.mean(axis=1)
        freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
        centroid = float((weights * freqs).sum() / max(weights.sum(), 1e-9))
        if centroid < 300:
            pitch = 36  # kick
            velocity = 110
        elif centroid < 1200:
            pitch = 38  # snare
            velocity = 100
        elif centroid < 3500:
            pitch = 42  # closed hi-hat
            velocity = 80
        else:
            pitch = 49  # crash
            velocity = 70
        notes.append(NoteEvent(time, time + 0.08, pitch, velocity, 0.3))

    note_events_to_midi(notes, out_midi, is_drum=True, bpm=bpm, name="drums")
    return notes, "drums-onset-fallback"
