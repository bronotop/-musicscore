"""Model registry loaded from models.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelSpec:
    id: str
    kind: str
    architecture: str = ""
    license: str = ""
    stems: list[str] = field(default_factory=list)
    sample_rate: int = 44100
    vram_gb: float = 0.0
    notes: str = ""


def load_registry(path: Path | None = None) -> dict[str, ModelSpec]:
    path = Path(path) if path else Path(__file__).with_name("models.yaml")
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs: dict[str, ModelSpec] = {}
    for key, value in (payload.get("models") or {}).items():
        specs[key] = ModelSpec(
            id=key,
            kind=value.get("kind", ""),
            architecture=value.get("architecture", ""),
            license=value.get("license", ""),
            stems=list(value.get("stems", [])),
            sample_rate=int(value.get("sample_rate", 44100)),
            vram_gb=float(value.get("vram_gb", 0)),
            notes=value.get("notes", ""),
        )
    return specs
