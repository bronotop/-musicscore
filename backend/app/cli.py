"""Command-line entry point.

Examples:
    python -m app.cli doctor
    python -m app.cli run song.mp3 --preset fast
    python -m app.cli run song.mp3 --only separate,transcribe --force
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from app.config import SETTINGS
from app.pipeline.context import ProjectContext
from app.pipeline.runner import run_pipeline


def slugify(text: str, max_length: int = 48) -> str:
    text = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-")
    return (text[:max_length] or "project").lower()


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = SETTINGS
    settings.ensure_dirs()

    print("music2score doctor")
    print(f"  python      : {sys.version.split()[0]} ({sys.executable})")
    print(f"  home        : {settings.home}")
    print(f"  models dir  : {settings.models_dir}")

    try:
        import torch

        print(f"  torch       : {torch.__version__}")
        print(f"  cuda        : {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            print(f"  gpu         : {props.name} ({props.total_memory / 1024**3:.1f} GB)")
    except Exception as exc:
        print(f"  torch       : unavailable ({exc})")

    from app.services.audio import ffmpeg_version, free_space_gb

    print(f"  ffmpeg      : {ffmpeg_version()}")

    from app.services.notation import find_musescore

    musescore = find_musescore(settings.musescore_path)
    print(f"  musescore   : {musescore or 'not found (PDF export disabled)'}")
    print(f"  free space  : {free_space_gb(settings.home):.1f} GB")

    checks = [
        ("audio_separator", "source separation"),
        ("basic_pitch", "Basic Pitch transcription"),
        ("transkun", "piano transcription"),
        ("beat_this", "beat/downbeat tracking"),
        ("muscriptor", "general transcription (optional)"),
        ("adtof_pytorch", "ADTOF drum transcription"),
        ("verovio", "SVG score preview (optional)"),
        ("faster_whisper", "lyrics transcription (optional)"),
    ]
    for module, purpose in checks:
        print(f"  {module:16}: {'ok' if module_available(module) else 'missing'} ({purpose})")

    try:
        from app.models.adapters.muscriptor import locate_weights

        weights = locate_weights()
    except Exception:
        weights = None
    print(f"  muscriptor wts  : {weights or 'not found (optional)'}")
    try:
        from app.models.adapters.lyrics import locate_model

        lyrics_model = locate_model()
    except Exception:
        lyrics_model = None
    print(f"  lyrics model    : {lyrics_model or 'not found (optional)'}")
    try:
        from app.models.adapters.game import locate_model as locate_game

        game_model = locate_game()
    except Exception:
        game_model = None
    print(f"  GAME model      : {game_model or 'not found (optional)'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    source = Path(args.audio).expanduser().resolve()
    if not source.exists():
        print(f"Input not found: {source}", file=sys.stderr)
        return 2

    settings = SETTINGS
    settings.ensure_dirs()

    project_id = args.project_id or f"{datetime.now():%Y%m%d-%H%M%S}_{slugify(source.stem)}"
    root = Path(args.project_dir).expanduser().resolve() if args.project_dir else settings.projects_dir / project_id

    mode = args.mode
    instrument_id = args.instrument
    if mode == "solo":
        if not instrument_id:
            print("--instrument is required with --mode solo", file=sys.stderr)
            return 2
        from app.instruments import REGISTRY

        profile = REGISTRY.resolve(instrument_id)
        if profile is None:
            print(f"Unknown instrument: {instrument_id}", file=sys.stderr)
            return 2
        instrument_id = profile.id

    ctx = ProjectContext(
        project_id=project_id,
        root=root,
        source=source,
        preset=args.preset,
        sample_rate=settings.sample_rate,
        channels=settings.channels,
        musescore_path=settings.musescore_path,
        log=print,
        mode=mode,
        instrument_id=instrument_id,
    )
    ctx.write_json(
        root / "project.json",
        {
            "project_id": project_id,
            "title": source.stem,
            "original_filename": source.name,
            "source": str(source),
            "source_path": str(source),
            "preset": args.preset,
            "mode": mode,
            "instrument_id": instrument_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

    only = {name.strip() for name in args.only.split(",")} if args.only else None
    results = run_pipeline(ctx, force=args.force, only=only)

    print("\nOutputs")
    for result in results.values():
        for logical, path in result.outputs.items():
            print(f"  {result.name:10} {logical:12} {path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    projects_dir = SETTINGS.projects_dir
    if not projects_dir.exists():
        print("No projects yet.")
        return 0
    for project in sorted(projects_dir.iterdir(), reverse=True):
        if not project.is_dir():
            continue
        meta_path = project / "project.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        print(f"{project.name}  {meta.get('source', '')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music2score")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check the local environment")
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="run the full transcription pipeline")
    run.add_argument("audio", help="input audio file (mp3, wav, flac, m4a, ...)")
    run.add_argument("--preset", choices=["fast", "quality"], default="fast")
    run.add_argument("--force", action="store_true", help="ignore cached stages")
    run.add_argument("--only", default=None, help="comma-separated stage names")
    run.add_argument("--project-id", default=None)
    run.add_argument("--project-dir", default=None)
    run.add_argument("--mode", choices=["full", "solo"], default="full")
    run.add_argument("--instrument", default=None, help="instrument id/name for solo mode")
    run.set_defaults(func=cmd_run)

    listing = sub.add_parser("list", help="list projects")
    listing.set_defaults(func=cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
