"""Source separation adapter built on python-audio-separator (MIT)."""

from __future__ import annotations

import inspect
import os
import shutil
from pathlib import Path
from typing import Callable

STEM_ALIASES: dict[str, tuple[str, ...]] = {
    "vocals": ("vocal", "voice"),
    "drums": ("drum",),
    "bass": ("bass",),
    "guitar": ("guitar",),
    "piano": ("piano",),
    "other": ("other", "instrumental", "accompaniment"),
}

MODEL_CANDIDATES: dict[str, list[str]] = {
    "fast": ["htdemucs_ft.yaml", "htdemucs.yaml"],
    # Quality prefers the 6-stem model so guitar/piano get their own stems.
    "quality": ["htdemucs_6s.yaml", "htdemucs_ft.yaml", "htdemucs.yaml"],
}

# Quality runs both Demucs variants: the fine-tuned 4-stem model gives better
# vocals/drums/bass/other, while htdemucs_6s is the only one with guitar/piano.
QUALITY_HYBRID_MODELS: tuple[str, ...] = ("htdemucs_6s.yaml", "htdemucs_ft.yaml")


def classify_stem(filename: str) -> str | None:
    name = Path(filename).stem.lower()
    for stem, aliases in STEM_ALIASES.items():
        if any(alias in name for alias in aliases):
            return stem
    return None


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _separator_kwargs(models_dir: Path, output_dir: Path, preset: str = "fast") -> dict:
    from audio_separator.separator import Separator

    quality = preset == "quality"
    # The quality preset is deliberately time-unconstrained: more random
    # shifts and a wider overlap window trade runtime for cleaner stems.
    default_shifts = 4 if quality else 1
    default_overlap = 0.5 if quality else 0.25
    wanted = {
        "model_file_dir": str(models_dir),
        "output_dir": str(output_dir),
        "output_format": "WAV",
        # CPU autocast falls back to emulated bfloat16 and is ~40x slower on
        # this class of CPU; only enable it when a real CUDA device is present.
        "use_autocast": _cuda_available(),
        "sample_rate": 44100,
        # The API default ('Default') skips Demucs' 7.8 s chunking and is far
        # slower on CPU than the CLI. Match the CLI's practical defaults.
        "demucs_params": {
            "segment_size": _env_float("DEMUCS_SEGMENT_SIZE", 7.8),
            "shifts": max(1, _env_int("DEMUCS_SHIFTS", default_shifts)),
            "overlap": min(0.9, max(0.0, _env_float("DEMUCS_OVERLAP", default_overlap))),
            "segments_enabled": True,
        },
    }
    signature = inspect.signature(Separator.__init__)
    return {key: value for key, value in wanted.items() if key in signature.parameters}


def _run_model(
    audio_path: Path,
    raw_output_dir: Path,
    stems_dir: Path,
    models_dir: Path,
    model_filename: str,
    preset: str,
    log: Callable[[str], None],
) -> dict[str, Path]:
    from audio_separator.separator import Separator

    raw_output_dir.mkdir(parents=True, exist_ok=True)
    separator = Separator(**_separator_kwargs(models_dir, raw_output_dir, preset))
    separator.load_model(model_filename=model_filename)
    produced = separator.separate(str(audio_path))
    return _copy_standard_stems(produced, raw_output_dir, stems_dir)


def _clear_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _separate_quality_hybrid(
    audio_path: Path,
    raw_output_dir: Path,
    stems_dir: Path,
    models_dir: Path,
    log: Callable[[str], None],
) -> tuple[dict[str, Path], str]:
    mapping: dict[str, Path] = {}
    used: list[str] = []
    errors: list[str] = []
    for model_filename in QUALITY_HYBRID_MODELS:
        try:
            log(f"    hybrid separation: {model_filename}")
            produced = _run_model(
                audio_path,
                raw_output_dir / Path(model_filename).stem,
                stems_dir,
                models_dir,
                model_filename,
                "quality",
                log,
            )
            if not produced:
                raise RuntimeError("no recognisable stems")
            mapping.update(produced)
            used.append(model_filename.removesuffix(".yaml"))
            _clear_cuda_cache()
        except Exception as exc:
            errors.append(f"{model_filename}: {type(exc).__name__}: {exc}")
            log(f"    hybrid model failed: {errors[-1]}")
    if mapping:
        return mapping, "+".join(used)
    raise RuntimeError(
        "Quality hybrid separation failed:\n  " + "\n  ".join(errors)
    )


def separate_to_stems(
    audio_path: Path,
    raw_output_dir: Path,
    stems_dir: Path,
    preset: str,
    models_dir: Path,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, Path], str]:
    """Run the selected separation strategy and return standard stem paths."""
    from app.services.audio import ensure_ffmpeg_on_path

    ensure_ffmpeg_on_path()

    audio_path = Path(audio_path)
    raw_output_dir = Path(raw_output_dir)
    stems_dir = Path(stems_dir)
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)

    if preset == "quality":
        return _separate_quality_hybrid(
            audio_path, raw_output_dir, stems_dir, models_dir, log
        )

    candidates = MODEL_CANDIDATES.get(preset, MODEL_CANDIDATES["fast"])
    errors: list[str] = []

    for model_filename in candidates:
        try:
            log(f"    separation model: {model_filename}")
            mapping = _run_model(
                audio_path,
                raw_output_dir,
                stems_dir,
                models_dir,
                model_filename,
                preset,
                log,
            )
            if mapping:
                return mapping, model_filename
            errors.append(f"{model_filename}: no recognisable stems")
        except Exception as exc:  # try the next candidate
            errors.append(f"{model_filename}: {type(exc).__name__}: {exc}")
            log(f"    model failed: {errors[-1]}")

    raise RuntimeError("All separation models failed:\n  " + "\n  ".join(errors))


def _copy_standard_stems(
    produced: list[str],
    raw_output_dir: Path,
    stems_dir: Path,
) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for filename in produced:
        path = Path(filename)
        if not path.is_absolute():
            path = raw_output_dir / path
        stem = classify_stem(path.name)
        if stem is None or stem in mapping:
            continue
        target = stems_dir / f"{stem}.wav"
        shutil.copy2(path, target)
        mapping[stem] = target
    return mapping
