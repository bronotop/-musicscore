"""MuScriptor general transcription adapter.

Weights are CC BY-NC 4.0 and hosted in gated HuggingFace repos. Put
``model.safetensors`` (and optionally ``config.json``) under
``<MUSIC2SCORE_HOME>/models/muscriptor/muscriptor-<size>/`` or point
``MUSCRIPTOR_WEIGHTS`` at the file/directory. Without weights the adapter raises
and the caller falls back to Basic Pitch / pitch tracking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import SETTINGS
from app.models.adapters.common import resolve_device
from app.types import NoteEvent

# Values from muscriptor.transcription_model._CONFIGS (0.4.0).
_CONFIGS: dict[str, dict[str, int]] = {
    "small": {"dim": 768, "num_heads": 12, "num_layers": 14, "card": 1393},
    "medium": {"dim": 1024, "num_heads": 16, "num_layers": 24, "card": 1395},
    "large": {"dim": 1536, "num_heads": 24, "num_layers": 48, "card": 1395},
}

_MODEL_CACHE: dict[tuple[str, str], object] = {}


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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _tempo_option():
    raw = (os.environ.get("MUSCRIPTOR_DETECT_TEMPO") or "").strip().lower()
    if not raw:
        return None
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return "best-effort" if raw == "best-effort" else None


def _iter_weight_files(root: Path):
    if not root.exists():
        return
    if root.is_file() and root.name.endswith(".safetensors"):
        yield root
        return
    for pattern in ("model.safetensors", "*.safetensors"):
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                yield path
        for path in sorted(root.glob(f"*/{pattern}")):
            if path.is_file():
                yield path
        for path in sorted(root.glob(f"*/*/{pattern}")):
            if path.is_file():
                yield path


def locate_weights() -> Path | None:
    """Find local MuScriptor weights, preferring an explicit env var."""
    explicit = os.environ.get("MUSCRIPTOR_WEIGHTS")
    if explicit:
        candidate = Path(explicit).expanduser()
        for path in _iter_weight_files(candidate):
            return path
    for path in _iter_weight_files(SETTINGS.models_dir / "muscriptor"):
        return path
    return None


def _infer_size(weights: Path) -> str:
    forced = os.environ.get("MUSCRIPTOR_SIZE")
    if forced in _CONFIGS:
        return forced
    text = str(weights).lower().replace("\\", "/")
    for size in ("large", "medium", "small"):
        if f"muscriptor-{size}" in text or f"/{size}/" in text:
            return size
    return "medium"


def _ensure_config(weights: Path, size: str) -> None:
    config_path = weights.parent / "config.json"
    if config_path.exists():
        return
    config_path.write_text(json.dumps(_CONFIGS[size]), encoding="utf-8")


def load_model(size: str | None = None):
    weights = locate_weights()
    if weights is None:
        raise FileNotFoundError(
            "MuScriptor weights not found. Download model.safetensors from "
            "https://huggingface.co/MuScriptor/muscriptor-medium into "
            f"{SETTINGS.models_dir / 'muscriptor' / 'muscriptor-medium'} "
            "or set MUSCRIPTOR_WEIGHTS."
        )
    resolved_size = size if size in _CONFIGS else _infer_size(weights)
    _ensure_config(weights, resolved_size)

    device = resolve_device("auto")
    key = (str(weights), device)
    if key not in _MODEL_CACHE:
        from muscriptor.transcription_model import TranscriptionModel

        _MODEL_CACHE[key] = TranscriptionModel.load_model(
            weights_path=str(weights),
            device=device,
            dtype=None,
        )
    return _MODEL_CACHE[key], resolved_size


def _read_notes(path: Path) -> list[NoteEvent]:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(path))
    return [
        NoteEvent(n.start, n.end, n.pitch, n.velocity, 1.0)
        for instrument in midi.instruments
        for n in instrument.notes
    ]


def transcribe(
    audio_path: Path,
    out_midi: Path,
    size: str | None = None,
    instruments: list[str] | None = None,
    quality: bool = False,
) -> tuple[list[NoteEvent], str]:
    from muscriptor.utils.midi import ExportOptions

    model, resolved_size = load_model(size=size)
    options: dict = {
        "instruments": instruments,
        "export": ExportOptions(quantize=True),
    }
    beam_size = _env_int("MUSCRIPTOR_BEAM_SIZE", 3 if quality else 1)
    if beam_size > 1:
        options["beam_size"] = min(16, beam_size)
    cfg_coef = _env_float("MUSCRIPTOR_CFG_COEF", 1.0)
    if cfg_coef != 1.0:
        options["cfg_coef"] = cfg_coef
    temperature = max(0.05, _env_float("MUSCRIPTOR_TEMPERATURE", 1.0))
    if temperature != 1.0:
        options["temperature"] = temperature
    if _env_bool("MUSCRIPTOR_USE_SAMPLING", False):
        options["use_sampling"] = True
    if not _env_bool("MUSCRIPTOR_PRELUDE_FORCING", True):
        options["prelude_forcing"] = False
    if not _env_bool("MUSCRIPTOR_NO_EOS_IS_OK", True):
        options["no_eos_is_ok"] = False
    batch_size = _env_int("MUSCRIPTOR_BATCH_SIZE", 0)
    if batch_size > 0:
        options["batch_size"] = batch_size
    tempo_option = _tempo_option()
    if tempo_option is not None:
        options["detect_tempo"] = tempo_option
    midi_bytes, _beat_grid = model.transcribe_and_postprocess(
        str(audio_path),
        **options,
    )
    out_midi = Path(out_midi)
    out_midi.parent.mkdir(parents=True, exist_ok=True)
    out_midi.write_bytes(midi_bytes)
    return _read_notes(out_midi), f"muscriptor-{resolved_size}"
