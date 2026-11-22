"""GAME (Generative Adaptive MIDI Extractor) ONNX adapter.

GAME is OpenVPI's singing-voice transcription model.  This adapter uses the
official ONNX release so inference needs only ``onnxruntime`` (no Lightning or
training dependencies).  The model is fully monophonic and predicts note
boundaries with a D3PM sampling loop, then estimates a continuous MIDI pitch for
each region.

Model: https://github.com/openvpi/GAME/releases/tag/v1.0.3
License: MIT (code and released checkpoints; no separate weights license)
Tested: GAME-1.0.3-medium-onnx, 49.9M parameters, Python 3.12,
onnxruntime 1.31.1 CPU provider, 8 GB GPU.

The official checkpoint expects 44.1 kHz mono audio.  Quiet stems are peak
normalised before inference because the encoder works on a log-mel spectrogram
and otherwise loses quiet material.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from app.models.adapters.common import MissingDependencyError, note_events_to_midi
from app.types import NoteEvent

REQUIRED_FILES = (
    "config.json",
    "encoder.onnx",
    "segmenter.onnx",
    "estimator.onnx",
)

_SESSIONS: dict[tuple[str, tuple[str, ...]], tuple[dict, dict]] = {}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _hz_to_midi(frequency: float) -> float:
    return 69.0 + 12.0 * np.log2(max(float(frequency), 1e-9) / 440.0)


def _candidate_dirs():
    configured = os.environ.get("VOCAL_GAME_MODEL") or os.environ.get("VOCAL_GAME_DIR")
    if configured:
        yield Path(configured).expanduser()
    try:
        from app.config import PROJECT_ROOT, SETTINGS

        yield SETTINGS.models_dir / "game"
        yield PROJECT_ROOT / "models" / "game"
    except Exception:
        pass
    yield Path.cwd() / "models" / "game"
    yield Path.cwd().parent / "models" / "game"


def locate_model() -> Path | None:
    """Return the directory containing a complete GAME ONNX export."""
    seen: set[Path] = set()
    for base in _candidate_dirs():
        base = Path(base)
        try:
            base = base.resolve()
        except OSError:
            pass
        if base in seen:
            continue
        seen.add(base)
        if base.is_file() and base.name == "encoder.onnx":
            base = base.parent
        if not base.is_dir():
            continue
        directories = [base]
        try:
            children = [
                path for path in base.iterdir() if path.is_dir()
            ]
            preferred = os.environ.get("VOCAL_GAME_SIZE", "medium").strip().lower()
            # Prefer a requested size, then medium/small/large, then name.
            size_rank = {"medium": 0, "small": 1, "large": 2}
            children.sort(
                key=lambda path: (
                    0 if preferred and preferred in path.name.lower() else 1,
                    size_rank.get(
                        next(
                            (
                                size
                                for size in size_rank
                                if size in path.name.lower()
                            ),
                            "",
                        ),
                        9,
                    ),
                    path.name,
                )
            )
            directories.extend(children)
        except OSError:
            pass
        for directory in directories:
            if all((directory / name).is_file() for name in REQUIRED_FILES):
                return directory
    return None


def available() -> bool:
    try:
        return locate_model() is not None
    except Exception:
        return False


def model_name(model_dir: Path) -> str:
    name = Path(model_dir).name.strip().lower().replace("_", "-")
    if not name.startswith("game"):
        name = f"game-{name}"
    return name


def _providers(device: str) -> list[str]:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise MissingDependencyError(
            "Missing dependency 'onnxruntime'. Install with: pip install onnxruntime"
        ) from exc
    available_providers = set(ort.get_available_providers())
    if device != "cpu" and "CUDAExecutionProvider" in available_providers:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def _load_sessions(model_dir: Path, device: str):
    import onnxruntime as ort

    providers = _providers(device)
    key = (str(Path(model_dir).resolve()), tuple(providers))
    cached = _SESSIONS.get(key)
    if cached is not None:
        return cached

    def make_options():
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        try:
            cpus = os.cpu_count() or 4
        except Exception:
            cpus = 4
        options.intra_op_num_threads = max(1, min(8, cpus))
        return options

    sessions = {
        name: ort.InferenceSession(
            str(Path(model_dir) / f"{name}.onnx"),
            sess_options=make_options(),
            providers=providers,
        )
        for name in ("encoder", "segmenter", "estimator")
    }
    config = json.loads((Path(model_dir) / "config.json").read_text(encoding="utf-8"))
    _SESSIONS[key] = (sessions, config)
    return sessions, config


def _load_audio(audio_path: Path, samplerate: int) -> np.ndarray | None:
    try:
        import librosa

        waveform, _ = librosa.load(str(audio_path), sr=int(samplerate), mono=True)
    except Exception as exc:
        raise MissingDependencyError(
            "GAME needs librosa to read audio. Install with: pip install librosa"
        ) from exc
    if waveform.size == 0:
        return None
    waveform = np.asarray(waveform, dtype=np.float32)
    waveform = waveform - float(np.mean(waveform))
    peak = float(np.max(np.abs(waveform)))
    if peak < 1e-6:
        return None
    # Peak normalisation is essential for quiet separation stems.  The
    # official inference code assumes reasonably mastered audio.
    return (waveform / peak * 0.9).astype(np.float32)


def _language_id(config: dict) -> int:
    raw = os.environ.get("VOCAL_GAME_LANGUAGE", "").strip().lower()
    if not raw:
        return 0
    languages = config.get("languages") or {}
    try:
        return int(languages.get(raw, 0))
    except (TypeError, ValueError):
        return 0


def _boundary_times(steps: int) -> list[float]:
    steps = max(1, min(64, int(steps)))
    t0 = min(max(_env_float("VOCAL_GAME_T0", 0.0), 0.0), 0.99)
    span = (1.0 - t0) / steps
    return [t0 + index * span for index in range(steps)]


def _infer_window(
    waveform: np.ndarray,
    sessions: dict,
    config: dict,
    steps: int = 8,
) -> list[NoteEvent]:
    if waveform.size == 0:
        return []
    samplerate = int(config.get("samplerate", 44100))
    timestep = float(config.get("timestep", 0.01))

    duration = np.array([len(waveform) / samplerate], dtype=np.float32)
    x_seg, x_est, mask_t = sessions["encoder"].run(
        None,
        {
            "waveform": waveform[None, :].astype(np.float32),
            "duration": duration,
        },
    )
    frame_count = int(mask_t.shape[1])
    if frame_count <= 0:
        return []

    known = np.zeros((1, frame_count), dtype=bool)
    previous = known.copy()
    language = np.array([_language_id(config)], dtype=np.int64)
    threshold = np.array(
        _env_float("VOCAL_GAME_BOUNDARY_THRESHOLD", 0.2), dtype=np.float32
    )
    radius = np.array(
        _env_int("VOCAL_GAME_BOUNDARY_RADIUS", 2), dtype=np.int64
    )

    segmenter_inputs = {
        item.name for item in sessions["segmenter"].get_inputs()
    }
    for time_value in _boundary_times(steps):
        feed = {
            "x_seg": x_seg,
            "known_boundaries": known,
            "maskT": mask_t,
            "threshold": threshold,
            "radius": radius,
        }
        if "language" in segmenter_inputs:
            feed["language"] = language
        if "prev_boundaries" in segmenter_inputs:
            feed["prev_boundaries"] = previous
        if "t" in segmenter_inputs:
            feed["t"] = np.array([time_value], dtype=np.float32)
        previous = sessions["segmenter"].run(None, feed)[0]

    regions = np.cumsum(previous.astype(np.int64), axis=-1) + 1
    regions = regions * mask_t.astype(np.int64)
    max_notes = int(regions.max()) if regions.size else 0
    if max_notes <= 0:
        return []

    mask_n = np.ones((1, max_notes), dtype=bool)
    presence, scores = sessions["estimator"].run(
        None,
        {
            "x_est": x_est,
            "boundaries": previous,
            "maskT": mask_t,
            "maskN": mask_n,
            "threshold": np.array(
                _env_float("VOCAL_GAME_PRESENCE_THRESHOLD", 0.2), dtype=np.float32
            ),
        },
    )

    counts = np.bincount(regions[0], minlength=max_notes + 1)[1:]
    durations = counts.astype(np.float32) * timestep
    onsets = np.concatenate([[0.0], np.cumsum(durations)[:-1]])

    notes: list[NoteEvent] = []
    for onset, note_duration, voiced, score in zip(
        onsets, durations, presence[0], scores[0]
    ):
        if not voiced or note_duration <= 0.0:
            continue
        pitch_value = float(score)
        if not np.isfinite(pitch_value) or pitch_value < 0.0:
            continue
        notes.append(
            NoteEvent(
                start=float(onset),
                end=float(onset + note_duration),
                pitch=int(round(pitch_value)),
                velocity=90,
                # GAME exposes presence as a boolean, not a calibrated score.
                # 0.85 marks model output without pretending to be a probability.
                confidence=0.85,
            )
        )
    return notes


def _stitch_notes(notes: list[NoteEvent]) -> list[NoteEvent]:
    """Merge notes from overlapping inference windows."""
    if not notes:
        return []
    notes = sorted(notes, key=lambda item: (item.start, item.end))
    result: list[NoteEvent] = []
    for note in notes:
        merged = False
        for previous in reversed(result):
            if previous.end <= note.start - 0.05:
                break
            overlap = min(previous.end, note.end) - max(previous.start, note.start)
            if overlap <= 0.03:
                continue
            if abs(previous.pitch - note.pitch) <= 1:
                previous.start = min(previous.start, note.start)
                previous.end = max(previous.end, note.end)
                previous.confidence = max(previous.confidence, note.confidence)
                merged = True
                break
            if (note.end - note.start) > (previous.end - previous.start):
                result.remove(previous)
                result.append(note)
            merged = True
            break
        if not merged:
            result.append(note)
    result.sort(key=lambda item: (item.start, item.end))
    return result


def _filter_frequency(
    notes: list[NoteEvent],
    min_frequency: float,
    max_frequency: float,
) -> list[NoteEvent]:
    low = _hz_to_midi(min_frequency)
    high = _hz_to_midi(max_frequency)
    return [
        note
        for note in notes
        if low - 0.5 <= note.pitch <= high + 0.5
    ]


def transcribe(
    audio_path: Path,
    out_midi: Path,
    bpm: float = 120.0,
    min_frequency: float = 80.0,
    max_frequency: float = 1200.0,
    device: str = "auto",
    quality: bool = False,
) -> tuple[list[NoteEvent], str]:
    """Transcribe one vocal stem with GAME.

    Raises ``MissingDependencyError`` when the model or onnxruntime is absent;
    the caller is expected to fall back to the heuristic path.
    """
    model_dir = locate_model()
    if model_dir is None:
        raise MissingDependencyError(
            "GAME model not found. Run scripts/download_game.py or set "
            "VOCAL_GAME_MODEL to a GAME-*-onnx directory."
        )

    sessions, config = _load_sessions(model_dir, device)
    samplerate = int(config.get("samplerate", 44100))
    waveform = _load_audio(audio_path, samplerate)
    name = model_name(model_dir)

    if waveform is None:
        note_events_to_midi([], out_midi, program=53, bpm=bpm, name="game")
        return [], name

    duration = len(waveform) / samplerate
    steps = max(
        1,
        min(64, _env_int("VOCAL_GAME_STEPS", 24 if quality else 8)),
    )
    default_window = 60.0 if quality else 45.0
    default_hop = 30.0 if quality else max(1.0, default_window - 2.0)
    window = max(4.0, _env_float("VOCAL_GAME_WINDOW_SEC", default_window))
    hop = max(1.0, _env_float("VOCAL_GAME_HOP_SEC", default_hop))
    if hop > window:
        hop = window

    notes: list[NoteEvent] = []
    if duration <= window + 0.5:
        notes = _infer_window(waveform, sessions, config, steps)
    else:
        starts = []
        position = 0.0
        while position + 0.25 < duration:
            starts.append(position)
            if position + window >= duration:
                break
            position += hop
        for start in starts:
            begin = int(round(start * samplerate))
            end = min(len(waveform), int(round((start + window) * samplerate)))
            chunk = waveform[begin:end]
            if chunk.size < int(0.25 * samplerate):
                continue
            local = _infer_window(chunk, sessions, config, steps)
            for note in local:
                note.start += start
                note.end += start
            notes.extend(local)
        notes = _stitch_notes(notes)

    notes = _filter_frequency(notes, min_frequency, max_frequency)
    notes.sort(key=lambda item: (item.start, item.end, item.pitch))
    note_events_to_midi(notes, out_midi, program=53, bpm=bpm, name="game")
    return notes, name
