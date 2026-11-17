"""Download a CTranslate2 Whisper model for the lyrics adapter.

The models are MIT-licensed and public on Hugging Face:
    https://huggingface.co/Systran/faster-whisper-small

Examples:
    python scripts/download_whisper.py --size small
    python scripts/download_whisper.py --size small --check

Weights go to ``$MUSIC2SCORE_HOME/models/faster-whisper/<size>``
(default home: ``<repository>/runtime``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SIZES = ("tiny", "base", "small", "medium", "large-v3")
REQUIRED = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def default_destination(size: str) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    home = Path(os.environ.get("MUSIC2SCORE_HOME", repo_root / "runtime")).expanduser()
    return home / "models" / "faster-whisper" / size


def is_complete(path: Path) -> bool:
    return all((path / name).is_file() for name in REQUIRED)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a faster-whisper model")
    parser.add_argument("--size", choices=SIZES, default="small")
    parser.add_argument("--dest", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="only verify existing files")
    parser.add_argument(
        "--repo",
        default="",
        help="override Hugging Face repo (default: Systran/faster-whisper-<size>)",
    )
    args = parser.parse_args()

    destination = (args.dest or default_destination(args.size)).expanduser().resolve()
    if args.check:
        if is_complete(destination):
            for name in REQUIRED:
                path = destination / name
                print(f"  {name:18s} {path.stat().st_size:>12,d} bytes")
            return 0
        print(f"incomplete Whisper model: {destination}", file=sys.stderr)
        return 1

    repo = args.repo or f"Systran/faster-whisper-{args.size}"
    destination.mkdir(parents=True, exist_ok=True)

    if is_complete(destination):
        print(f"Whisper model already present: {destination}")
        for name in REQUIRED:
            path = destination / name
            print(f"  {name:18s} {path.stat().st_size:>12,d} bytes")
        return 0

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        print(f"missing dependency 'huggingface_hub': {exc}", file=sys.stderr)
        print("install with: pip install huggingface-hub", file=sys.stderr)
        return 1

    print(f"downloading {repo} -> {destination}")
    endpoints = []
    if os.environ.get("HF_ENDPOINT"):
        endpoints.append(os.environ["HF_ENDPOINT"])
    else:
        endpoints.extend([None, "https://hf-mirror.com"])

    last_error: Exception | None = None
    for index, endpoint in enumerate(endpoints):
        label = endpoint or "https://huggingface.co"
        if index > 0:
            print(f"official endpoint failed; retrying with {label} ...")
        try:
            snapshot_download(
                repo_id=repo,
                local_dir=str(destination),
                allow_patterns=list(REQUIRED),
                endpoint=endpoint,
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            print(f"  {label} failed: {exc}", file=sys.stderr)

    if last_error is not None:
        print(f"download failed: {last_error}", file=sys.stderr)
        print(
            "Set HF_ENDPOINT to a mirror (for example https://hf-mirror.com), "
            "or download the files manually; see docs/MODEL_DOWNLOADS.md.",
            file=sys.stderr,
        )
        return 1

    missing = [name for name in REQUIRED if not (destination / name).is_file()]
    if missing:
        print(f"download incomplete, missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    print("done:")
    for name in REQUIRED:
        path = destination / name
        print(f"  {name:18s} {path.stat().st_size:>12,d} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
