"""Stage protocol shared by all pipeline steps."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.pipeline.context import ProjectContext


@dataclass
class StageResult:
    name: str
    key: str
    outputs: dict[str, Path]
    metrics: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    elapsed: float = 0.0


class Stage(ABC):
    name: str

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        return []

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict[str, Any]:
        return {}

    @abstractmethod
    def execute(
        self,
        ctx: ProjectContext,
        upstream: dict[str, StageResult],
    ) -> tuple[dict[str, Path], dict[str, Any]]:
        """Run the stage and return (outputs by logical name, metrics)."""
        raise NotImplementedError
