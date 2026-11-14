"""Per-project paths and logging context."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class ProjectContext:
    project_id: str
    root: Path
    source: Path
    preset: str = "fast"
    sample_rate: int = 44100
    channels: int = 2
    musescore_path: str | None = None
    log: Callable[[str], None] = print
    progress: Callable[[dict], None] | None = None
    extra: dict = field(default_factory=dict)
    mode: str = "full"
    instrument_id: str | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.source = Path(self.source)
        for path in (
            self.root,
            self.stems_dir,
            self.midi_model_dir,
            self.midi_final_dir,
            self.score_dir,
            self.exports_dir,
            self.cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def source_wav(self) -> Path:
        return self.root / "source.wav"

    @property
    def stems_dir(self) -> Path:
        return self.root / "stems"

    @property
    def analysis_path(self) -> Path:
        return self.root / "analysis.json"

    @property
    def midi_model_dir(self) -> Path:
        return self.root / "midi" / "model"

    @property
    def midi_final_dir(self) -> Path:
        return self.root / "midi" / "final"

    @property
    def score_dir(self) -> Path:
        return self.root / "score"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def stem_path(self, stem: str) -> Path:
        return self.stems_dir / f"{stem}.wav"

    def report_progress(self, fraction: float, message: str | None = None) -> None:
        """Report sub-stage progress (0..1) to the worker, when attached."""
        if self.progress is None:
            return
        self.progress(
            {
                "event": "stage_progress",
                "fraction": max(0.0, min(1.0, float(fraction))),
                "message": message,
            }
        )

    def write_json(self, path: Path, payload: dict) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_json(self, path: Path, default: dict | None = None) -> dict:
        path = Path(path)
        if not path.exists():
            return default or {}
        return json.loads(path.read_text(encoding="utf-8"))
