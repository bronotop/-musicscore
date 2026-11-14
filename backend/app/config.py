"""Global configuration for music2score.

The runtime directory (models, project data, caches) is configurable through
MUSIC2SCORE_HOME so large model weights can live on a different drive than
the source tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("MUSIC2SCORE_HOME", PROJECT_ROOT / "runtime")).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    home: Path = HOME
    sample_rate: int = 44100
    channels: int = 2
    preset: str = "fast"
    device: str = os.environ.get("MUSIC2SCORE_DEVICE", "auto")
    musescore_path: str | None = os.environ.get("MUSESCORE_PATH")

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    def ensure_dirs(self) -> None:
        for path in (self.models_dir, self.data_dir, self.cache_dir, self.logs_dir, self.projects_dir):
            path.mkdir(parents=True, exist_ok=True)


SETTINGS = Settings()
