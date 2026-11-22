"""Optional lyrics transcription with faster-whisper.

The model is intentionally not downloaded at runtime: put a CTranslate2 Whisper
model directory (``model.bin`` + ``config.json`` + ``tokenizer.json`` +
``vocabulary.txt``) under ``<MUSIC2SCORE_HOME>/models/faster-whisper/<size>``.
``tiny`` is enough to smoke-test; ``small`` or ``medium`` is recommended for
real songs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import SETTINGS

DEFAULT_SIZE = "small"
_CACHE: dict[tuple[str, str, str], object] = {}


def locate_model(size: str | None = None) -> Path | None:
    """Find a local faster-whisper model directory."""
    root = SETTINGS.models_dir / "faster-whisper"
    requested = size or os.environ.get("LYRICS_MODEL") or DEFAULT_SIZE
    candidates: list[Path] = []
    if requested:
        candidates.append(root / requested)
    if root.exists():
        for path in sorted(root.iterdir()):
            if path.is_dir() and path not in candidates:
                candidates.append(path)
    for candidate in candidates:
        if (candidate / "model.bin").is_file():
            return candidate
    return None


def _load_model(path: Path, device: str):
    from faster_whisper import WhisperModel

    compute_type = "float16" if device == "cuda" else "int8"
    key = (str(path), device, compute_type)
    if key not in _CACHE:
        _CACHE[key] = WhisperModel(
            str(path),
            device=device,
            compute_type=compute_type,
        )
    return _CACHE[key]


def _largest_installed_model() -> str | None:
    root = SETTINGS.models_dir / "faster-whisper"
    if not root.exists():
        return None
    best_name: str | None = None
    best_size = 0
    for path in root.iterdir():
        model_bin = path / "model.bin"
        if not path.is_dir() or not model_bin.is_file():
            continue
        size = model_bin.stat().st_size
        if size > best_size:
            best_name = path.name
            best_size = size
    return best_name


def transcribe(
    audio_path: Path,
    out_json: Path,
    model_size: str | None = None,
    language: str | None = None,
    device: str | None = None,
    quality: bool = False,
) -> tuple[dict, str]:
    """Transcribe lyrics with word timestamps and write a JSON sidecar."""
    import librosa

    if model_size is None and quality and not os.environ.get("LYRICS_MODEL"):
        model_size = _largest_installed_model()
    model_path = locate_model(model_size)
    if model_path is None:
        raise FileNotFoundError(
            "No faster-whisper model found under "
            f"{SETTINGS.models_dir / 'faster-whisper'}. "
            "Download a CTranslate2 Whisper model there or set LYRICS_MODEL."
        )

    preferred = device or os.environ.get("LYRICS_DEVICE") or "cpu"
    audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)
    if audio.size == 0:
        raise RuntimeError("empty audio for lyrics transcription")

    def run(selected_device: str):
        model = _load_model(model_path, selected_device)
        try:
            beam_size = int(os.environ.get("LYRICS_BEAM_SIZE", "8" if quality else "5"))
        except ValueError:
            beam_size = 8 if quality else 5
        segments, info = model.transcribe(
            audio.astype("float32"),
            language=language or os.environ.get("LYRICS_LANGUAGE") or None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=max(1, beam_size),
            condition_on_previous_text=False,
        )
        return segments, info

    try:
        segments, info = run(preferred)
    except Exception:
        if preferred == "cpu":
            raise
        segments, info = run("cpu")

    payload = {
        "model": model_path.name,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "segments": [],
    }
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        words = [
            {
                "start": round(float(word.start), 4),
                "end": round(float(word.end), 4),
                "word": word.word,
            }
            for word in (segment.words or [])
        ]
        payload["segments"].append(
            {
                "start": round(float(segment.start), 4),
                "end": round(float(segment.end), 4),
                "text": text,
                "words": words,
            }
        )

    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload, f"faster-whisper-{model_path.name}"
