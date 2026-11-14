"""Separate the mix into instrument stems."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.config import SETTINGS
from app.instruments import REGISTRY
from app.models.adapters.common import empty_cuda_cache
from app.models.adapters.separation import (
    MODEL_CANDIDATES,
    QUALITY_HYBRID_MODELS,
    separate_to_stems,
)
from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult


class SeparateStage(Stage):
    name = "separate"

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        return [ctx.source_wav]

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict:
        models = (
            list(QUALITY_HYBRID_MODELS)
            if ctx.preset == "quality"
            else MODEL_CANDIDATES.get(ctx.preset, MODEL_CANDIDATES["fast"])
        )
        return {
            "preset": ctx.preset,
            "mode": ctx.mode,
            "instrument_id": ctx.instrument_id,
            "models": models,
            "segment_size": os.environ.get("DEMUCS_SEGMENT_SIZE", "7.8"),
            "shifts": os.environ.get(
                "DEMUCS_SHIFTS", "4" if ctx.preset == "quality" else "1"
            ),
            "overlap": os.environ.get(
                "DEMUCS_OVERLAP", "0.5" if ctx.preset == "quality" else "0.25"
            ),
            "sample_rate": ctx.sample_rate,
        }

    def execute(self, ctx: ProjectContext, upstream: dict[str, StageResult]):
        if ctx.mode == "solo":
            profile = REGISTRY.resolve(ctx.instrument_id, default=True)
            target = ctx.stem_path(profile.id)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ctx.source_wav, target)
            ctx.log(f"    solo mode: {profile.name_en} ({profile.id})")
            return {"solo": target}, {
                "model": "solo-input",
                "mode": "solo",
                "instrument_id": profile.id,
                "stems": [profile.id],
                "stem_count": 1,
            }

        empty_cuda_cache()
        outputs, model = separate_to_stems(
            audio_path=ctx.source_wav,
            raw_output_dir=ctx.stems_dir / "raw",
            stems_dir=ctx.stems_dir,
            preset=ctx.preset,
            models_dir=SETTINGS.models_dir,
            log=ctx.log,
        )
        ctx.log(f"    stems: {', '.join(sorted(outputs))} ({model})")
        return outputs, {
            "model": model,
            "stems": sorted(outputs),
            "stem_count": len(outputs),
        }
