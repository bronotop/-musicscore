from __future__ import annotations

from app.pipeline.context import ProjectContext
from app.pipeline.runner import run_pipeline
from app.pipeline.stages.base import Stage


def _context(tmp_path):
    return ProjectContext(
        project_id="progress",
        root=tmp_path / "project",
        source=tmp_path / "project" / "source.wav",
        log=lambda *_: None,
    )


def test_context_progress_is_optional(tmp_path):
    ctx = _context(tmp_path)
    ctx.report_progress(0.5, "half")  # no callback attached: no-op


def test_runner_maps_stage_fraction_to_overall_event(tmp_path):
    ctx = _context(tmp_path)
    events: list[dict] = []

    class DemoStage(Stage):
        name = "demo"

        def execute(self, ctx, upstream):
            ctx.report_progress(0.5, "halfway")
            return {}, {}

    run_pipeline(ctx, stages=[DemoStage()], progress=events.append)

    kinds = [event["event"] for event in events]
    assert kinds == ["stage_start", "stage_progress", "stage_done", "pipeline_done"]
    sub = events[1]
    assert sub["fraction"] == 0.5
    assert sub["stage"] == "demo"
    assert (sub["index"], sub["total"]) == (1, 1)
    assert sub["message"] == "halfway"
