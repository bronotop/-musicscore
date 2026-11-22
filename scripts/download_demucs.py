"""Pre-download the Demucs checkpoints used by audio-separator.

Examples:
    python scripts/download_demucs.py
    python scripts/download_demucs.py --check

Weights go to ``$MUSIC2SCORE_HOME/models`` (default: ``<repository>/runtime/models``).
audio-separator can also download them automatically on first separation; this
script is for one-click installs and offline preparation.
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
from pathlib import Path

# Primary models used by the fast/quality presets. htdemucs.yaml is only a
# last-resort fallback and may not be reachable from all networks; skip it.
MODELS = ("htdemucs_ft.yaml", "htdemucs_6s.yaml")

# Tiny model-group configs. Writing them locally avoids a GitHub round-trip;
# the actual .th weights still come from the upstream model URL.
YAML_CONTENT = {
    "htdemucs_6s.yaml": "models: ['5c90dfd2']\n",
    "htdemucs_ft.yaml": (
        "models: ['f7e0c4bc', 'd12395a8', '92cfc3b6', '04573f0d']\n"
        "weights: [\n"
        "  [1., 0., 0., 0.],\n"
        "  [0., 1., 0., 0.],\n"
        "  [0., 0., 1., 0.],\n"
        "  [0., 0., 0., 1.],\n"
        "]\n"
    ),
}


def default_models_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    home = Path(os.environ.get("MUSIC2SCORE_HOME", repo_root / "runtime")).expanduser()
    return home / "models"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Demucs checkpoints")
    parser.add_argument("--models-dir", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="only list existing files")
    args = parser.parse_args()

    models_dir = (args.models_dir or default_models_dir()).expanduser().resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    if args.check:
        found = sorted(models_dir.glob("*.th")) + sorted(models_dir.glob("*.yaml"))
        if not found:
            print(f"no Demucs files under {models_dir}", file=sys.stderr)
            return 1
        for path in found:
            print(f"  {path.name:32s} {path.stat().st_size:>12,d} bytes")
        return 0

    temp_output = models_dir / "_download_tmp"
    temp_output.mkdir(parents=True, exist_ok=True)

    # Write the tiny model-group configs locally so audio-separator does not
    # have to fetch them from GitHub.
    for name, content in YAML_CONTENT.items():
        path = models_dir / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    try:
        from audio_separator.separator import Separator
    except Exception as exc:
        print(f"missing dependency 'audio-separator': {exc}", file=sys.stderr)
        print("install with: pip install -r requirements.txt", file=sys.stderr)
        return 1

    # audio-separator shells out to `ffmpeg`; expose imageio-ffmpeg on PATH.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.services.audio import ensure_ffmpeg_on_path

        ensure_ffmpeg_on_path()
    except Exception as exc:
        print(f"warning: could not prepare ffmpeg: {exc}", file=sys.stderr)

    ok = 0
    for model in MODELS:
        print(f"downloading/loading {model}")
        try:
            separator = Separator(
                model_file_dir=str(models_dir),
                output_dir=str(temp_output),
                output_format="WAV",
            )
            separator.load_model(model_filename=model)
            ok += 1
        except Exception as exc:
            print(f"  skipped {model}: {exc}", file=sys.stderr)
        finally:
            try:
                del separator
            except Exception:
                pass
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    try:
        temp_output.rmdir()
    except OSError:
        pass

    if ok == 0:
        print("no Demucs model could be downloaded", file=sys.stderr)
        return 1

    print("done; model files:")
    for path in sorted(models_dir.glob("*.th")) + sorted(models_dir.glob("*.yaml")):
        print(f"  {path.name:32s} {path.stat().st_size:>12,d} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
