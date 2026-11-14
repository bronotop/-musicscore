"""Run the downstream pipeline (analysis -> transcription -> notation) on
pre-separated stems, bypassing the separation model.

Usage:
    python scripts/downstream_smoke.py \
        --mix runtime/data/test/synth-pop.wav \
        --stems runtime/data/test/synth-pop_stems \
        --project runtime/data/projects/smoke-synth-pop
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from app.pipeline.context import ProjectContext
from app.pipeline.runner import run_pipeline
from app.pipeline.stages.analyze import AnalyzeStage
from app.pipeline.stages.assemble import AssembleStage
from app.pipeline.stages.notate import NotateStage
from app.pipeline.stages.transcribe import TranscribeStage
from app.types import STEMS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mix", required=True)
    parser.add_argument("--stems", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--preset", default="custom")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    mix = Path(args.mix).resolve()
    stems = Path(args.stems).resolve()
    project = Path(args.project).resolve()

    ctx = ProjectContext(
        project_id=project.name,
        root=project,
        source=mix,
        preset=args.preset,
        log=print,
    )

    shutil.copy2(mix, ctx.source_wav)
    for stem in STEMS:
        source = stems / f"{stem}.wav"
        if source.exists():
            shutil.copy2(source, ctx.stem_path(stem))
            print(f"stem: {stem} <- {source.name}")

    stages = [AnalyzeStage(), TranscribeStage(), AssembleStage(), NotateStage()]
    started = time.perf_counter()
    results = run_pipeline(ctx, stages=stages, force=args.force)
    elapsed = time.perf_counter() - started

    print("\nResult")
    for result in results.values():
        print(f"{result.name:10} cached={result.cached} elapsed={result.elapsed:.1f}s")
        for key, path in result.outputs.items():
            print(f"    {key:12} {path}")
    print(f"\ntotal {elapsed:.1f}s")


if __name__ == "__main__":
    main()
