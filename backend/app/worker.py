"""Background worker: runs one project pipeline in its own process.

The API starts this module via subprocess so GPU memory and crashes are
isolated from the web server. Progress is written atomically to job.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app.config import SETTINGS
from app.pipeline.context import ProjectContext
from app.pipeline.runner import run_pipeline


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_status(root: Path, payload: dict) -> None:
    payload["updated_at"] = utcnow()
    target = root / "job.json"
    tmp = root / "job.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.replace(target)
    except PermissionError:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--preset", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", default=None, help="comma-separated stage names")
    args = parser.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    meta = json.loads((root / "project.json").read_text(encoding="utf-8"))
    preset = args.preset or meta.get("preset", "fast")
    source = Path(meta["source_path"]).expanduser().resolve()

    state: dict = {
        "status": "running",
        "stage": None,
        "index": 0,
        "total": 0,
        "progress": 0,
        "pid": os.getpid(),
        "started_at": utcnow(),
        "message": "starting",
    }

    def status(**updates) -> None:
        state.update(updates)
        write_status(root, dict(state))

    def log(message: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {message}"
        print(line, flush=True)
        with (root / "job.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        state["message"] = line
        write_status(root, dict(state))

    def progress(event: dict) -> None:
        if event.get("event") == "stage_start":
            total = max(int(event.get("total", 1)), 1)
            status(
                stage=event.get("stage"),
                index=event.get("index", 0),
                total=total,
                progress=round((int(event.get("index", 1)) - 1) / total * 100),
                message=f"running {event.get('stage')}",
            )
        elif event.get("event") == "stage_progress":
            total = max(int(event.get("total") or state.get("total") or 1), 1)
            index = max(int(event.get("index") or state.get("index") or 1), 1)
            fraction = min(max(float(event.get("fraction") or 0.0), 0.0), 1.0)
            update: dict = {
                "progress": round(((index - 1) + fraction) / total * 100)
            }
            message = event.get("message")
            if message:
                update["message"] = message
            status(**update)
        elif event.get("event") == "stage_done":
            total = max(int(event.get("total", 1)), 1)
            status(
                stage=event.get("stage"),
                index=event.get("index", 0),
                total=total,
                progress=round(int(event.get("index", 1)) / total * 100),
                cached=bool(event.get("cached")),
                stage_seconds=event.get("elapsed"),
            )
        elif event.get("event") == "pipeline_done":
            status(progress=100)

    ctx = ProjectContext(
        project_id=meta.get("project_id", root.name),
        root=root,
        source=source,
        preset=preset,
        sample_rate=SETTINGS.sample_rate,
        channels=SETTINGS.channels,
        musescore_path=SETTINGS.musescore_path,
        log=log,
        mode=str(meta.get("mode") or "full"),
        instrument_id=meta.get("instrument_id"),
    )

    status(status="running", message="starting", progress=0)

    try:
        only = {name.strip() for name in args.only.split(",")} if args.only else None
        results = run_pipeline(ctx, force=args.force, progress=progress, only=only)
        summary = {
            name: {
                "cached": result.cached,
                "elapsed": round(result.elapsed, 2),
                "metrics": result.metrics,
                "outputs": {key: str(value) for key, value in result.outputs.items()},
            }
            for name, result in results.items()
        }
        status(
            status="done",
            stage=None,
            progress=100,
            message="done",
            finished_at=utcnow(),
            summary=summary,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - report any pipeline failure to the UI
        log(traceback.format_exc())
        status(
            status="error",
            message=f"{type(exc).__name__}: {exc}",
            finished_at=utcnow(),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
