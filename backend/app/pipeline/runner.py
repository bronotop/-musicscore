"""Sequential, resumable pipeline runner."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from app.pipeline.cache import StageCache, StageManifest
from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult
from app.types import relpath


def default_stages() -> list[Stage]:
    # Imported lazily so `doctor` and unit tests do not load ML dependencies.
    from app.pipeline.stages.analyze import AnalyzeStage
    from app.pipeline.stages.assemble import AssembleStage
    from app.pipeline.stages.ingest import IngestStage
    from app.pipeline.stages.notate import NotateStage
    from app.pipeline.stages.separate import SeparateStage
    from app.pipeline.stages.transcribe import TranscribeStage

    return [
        IngestStage(),
        AnalyzeStage(),
        SeparateStage(),
        TranscribeStage(),
        AssembleStage(),
        NotateStage(),
    ]


def run_pipeline(
    ctx: ProjectContext,
    stages: list[Stage] | None = None,
    force: bool = False,
    only: set[str] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, StageResult]:
    stages = stages or default_stages()
    if only:
        stages = [stage for stage in stages if stage.name in only]

    cache = StageCache(ctx.cache_dir)
    results: dict[str, StageResult] = {}
    run_log: list[dict[str, Any]] = []
    started = time.perf_counter()

    for index, stage in enumerate(stages, start=1):
        if progress:
            # Let stages report progress inside a long-running step (e.g. one
            # stem at a time during transcription).
            def _stage_progress(
                event: dict,
                _name: str = stage.name,
                _index: int = index,
                _total: int = len(stages),
            ) -> None:
                progress(
                    {
                        "event": "stage_progress",
                        "stage": _name,
                        "index": _index,
                        "total": _total,
                        **event,
                    }
                )

            ctx.progress = _stage_progress
        else:
            ctx.progress = None
        if progress:
            progress(
                {
                    "event": "stage_start",
                    "stage": stage.name,
                    "index": index,
                    "total": len(stages),
                }
            )
        ctx.log(f"[{index}/{len(stages)}] {stage.name}")
        inputs = stage.input_files(ctx, results)
        params = stage.params(ctx, results)
        key = cache.key(stage.name, inputs, params)
        manifest = None if force else cache.load(stage.name, key)

        if manifest is not None:
            outputs = {name: ctx.root / rel for name, rel in manifest.outputs.items()}
            missing = [path for path in outputs.values() if not path.exists()]
            if not missing:
                result = StageResult(
                    name=stage.name,
                    key=key,
                    outputs=outputs,
                    metrics=manifest.metrics,
                    cached=True,
                )
                results[stage.name] = result
                run_log.append(
                    {
                        "stage": stage.name,
                        "cached": True,
                        "key": key,
                        "elapsed": 0.0,
                        "metrics": manifest.metrics,
                    }
                )
                ctx.log(f"    cached ({key[:8]})")
                if progress:
                    progress(
                        {
                            "event": "stage_done",
                            "stage": stage.name,
                            "index": index,
                            "total": len(stages),
                            "cached": True,
                            "elapsed": 0.0,
                        }
                    )
                continue

        t0 = time.perf_counter()
        outputs, metrics = stage.execute(ctx, results)
        elapsed = time.perf_counter() - t0

        manifest = StageManifest(
            stage=stage.name,
            key=key,
            outputs={name: relpath(path, ctx.root) for name, path in outputs.items()},
            metrics=metrics,
            params=params,
        )
        cache.save(manifest)

        results[stage.name] = StageResult(
            name=stage.name,
            key=key,
            outputs=outputs,
            metrics=metrics,
            cached=False,
            elapsed=elapsed,
        )
        run_log.append(
            {
                "stage": stage.name,
                "cached": False,
                "key": key,
                "elapsed": round(elapsed, 2),
                "metrics": metrics,
            }
        )
        ctx.log(f"    done in {elapsed:.1f}s")
        if progress:
            progress(
                {
                    "event": "stage_done",
                    "stage": stage.name,
                    "index": index,
                    "total": len(stages),
                    "cached": False,
                    "elapsed": round(elapsed, 2),
                    "metrics": metrics,
                }
            )

    total = time.perf_counter() - started
    ctx.write_json(
        ctx.root / "run.json",
        {
            "project_id": ctx.project_id,
            "preset": ctx.preset,
            "total_seconds": round(total, 2),
            "stages": run_log,
        },
    )
    ctx.log(f"pipeline finished in {total:.1f}s")
    if progress:
        progress({"event": "pipeline_done", "total_seconds": round(total, 2)})
    return results
