"""Decode the uploaded file into a canonical 44.1 kHz WAV."""

from __future__ import annotations

from pathlib import Path

from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult
from app.services.audio import decode_to_wav, probe


class IngestStage(Stage):
    name = "ingest"

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        return [ctx.source]

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict:
        return {"sample_rate": ctx.sample_rate, "channels": ctx.channels}

    def execute(self, ctx: ProjectContext, upstream: dict[str, StageResult]):
        ctx.log(f"    decoding {ctx.source.name}")
        decode_to_wav(
            ctx.source,
            ctx.source_wav,
            sample_rate=ctx.sample_rate,
            channels=ctx.channels,
        )
        info = probe(ctx.source_wav)
        return {"audio": ctx.source_wav}, info.to_dict()
