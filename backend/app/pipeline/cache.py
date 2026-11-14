"""Content-addressed stage cache for resumable pipelines."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHUNK = 1024 * 1024


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(stage: str, files: list[Path], params: dict[str, Any] | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(stage.encode("utf-8"))
    digest.update(json.dumps(params or {}, sort_keys=True, default=str).encode("utf-8"))
    for path in files:
        path = Path(path)
        digest.update(path.name.encode("utf-8"))
        if path.exists() and path.is_file():
            digest.update(file_hash(path).encode("ascii"))
        else:
            digest.update(b"missing")
    return digest.hexdigest()[:24]


@dataclass
class StageManifest:
    stage: str
    key: str
    outputs: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "StageManifest":
        return cls(
            stage=payload["stage"],
            key=payload["key"],
            outputs=payload.get("outputs", {}),
            metrics=payload.get("metrics", {}),
            params=payload.get("params", {}),
            created_at=payload.get("created_at", ""),
        )


class StageCache:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, stage: str) -> Path:
        return self.root / stage / "manifest.json"

    def key(self, stage: str, files: list[Path], params: dict[str, Any] | None = None) -> str:
        return cache_key(stage, files, params)

    def load(self, stage: str, key: str) -> StageManifest | None:
        path = self._manifest_path(stage)
        if not path.exists():
            return None
        try:
            manifest = StageManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError):
            return None
        if manifest.key != key or manifest.stage != stage:
            return None
        return manifest

    def save(self, manifest: StageManifest) -> Path:
        path = self._manifest_path(manifest.stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
