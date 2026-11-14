"""Global beat/downbeat/tempo and key analysis."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.models.adapters.common import resolve_device
from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult
from app.services.quantize import infer_time_signature

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_beats(audio_path: Path, device: str = "auto") -> tuple[np.ndarray, np.ndarray, str, str | None]:
    import os

    if os.environ.get("MUSIC2SCORE_FORCE_LIBROSA") == "1":
        raise RuntimeError("MUSIC2SCORE_FORCE_LIBROSA=1")

    device = resolve_device(device)
    try:
        from beat_this.inference import File2Beats

        file2beats = File2Beats(checkpoint_path="final0", device=device, dbn=False)
        beats, downbeats = file2beats(str(audio_path))
        beats = np.asarray(beats, dtype=float)
        downbeats = np.asarray(downbeats, dtype=float)
        if len(beats) >= 2:
            return np.sort(beats), np.sort(downbeats), "beat_this", None
        raise RuntimeError("Beat-This returned fewer than two beats")
    except Exception as exc:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        beats = librosa.frames_to_time(beat_frames, sr=sr)
        if len(beats) < 2:
            raise RuntimeError(f"Beat tracking failed: {exc}") from exc
        downbeats = beats[::4]
        return np.sort(beats), np.sort(downbeats), "librosa", f"{type(exc).__name__}: {exc}"


def detect_key(audio_path: Path) -> tuple[str, float]:
    import librosa

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    vector = chroma.mean(axis=1)
    if not np.isfinite(vector).all() or vector.sum() <= 0:
        return "C major", 0.0
    vector = (vector - vector.mean()) / (vector.std() + 1e-9)

    best_score = -1e9
    best_label = "C major"
    for index in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            rotated = np.roll(profile, index)
            rotated = (rotated - rotated.mean()) / (rotated.std() + 1e-9)
            score = float(np.dot(vector, rotated) / 12.0)
            if score > best_score:
                best_score = score
                best_label = f"{NOTE_NAMES[index]} {mode}"
    return best_label, best_score


class AnalyzeStage(Stage):
    name = "analyze"

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        return [ctx.source_wav]

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict:
        return {"beat_model": "beat_this", "key_method": "krumhansl-chroma", "device": "auto"}

    def execute(self, ctx: ProjectContext, upstream: dict[str, StageResult]):
        beats, downbeats, source, warning = detect_beats(ctx.source_wav)
        if len(downbeats) == 0:
            downbeats = beats[::4]

        intervals = np.diff(beats)
        bpm = float(60.0 / np.median(intervals)) if len(intervals) else 120.0
        time_signature, ts_confidence = infer_time_signature(beats.tolist(), downbeats.tolist())
        key, key_confidence = detect_key(ctx.source_wav)

        payload = {
            "bpm": round(bpm, 2),
            "beats": [round(float(value), 4) for value in beats],
            "downbeats": [round(float(value), 4) for value in downbeats],
            "time_signature": time_signature,
            "time_signature_confidence": ts_confidence,
            "key": key,
            "key_confidence": round(float(key_confidence), 4),
            "beat_source": source,
            "beat_warning": warning,
        }
        ctx.write_json(ctx.analysis_path, payload)
        ctx.log(
            f"    {bpm:.1f} BPM, {time_signature}, {key}, "
            f"{len(beats)} beats ({source})"
        )
        return {"analysis": ctx.analysis_path}, {
            "bpm": payload["bpm"],
            "time_signature": time_signature,
            "key": key,
            "beat_source": source,
            "beat_count": int(len(beats)),
        }
