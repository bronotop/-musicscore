"""Piano transcription via Transkun V2 (MIT).

Transkun ships pretrained weights with the pip package and exposes a
`transkun <audio> <midi> --device cuda` CLI. We prefer that CLI because the
Python module is organised as internal submodules.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.models.adapters.common import (
    MissingDependencyError,
    require,
    resolve_device,
)
from app.types import NoteEvent


def _transkun_executable() -> list[str]:
    candidates = [
        Path(sys.executable).with_name("transkun.exe"),
        Path(sys.executable).with_name("transkun"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    found = shutil.which("transkun")
    if found:
        return [found]
    return [sys.executable, "-m", "transkun"]


def transcribe(
    audio_path: Path,
    out_midi: Path,
    device: str = "auto",
) -> tuple[list[NoteEvent], str]:
    require("transkun", "Install with: pip install transkun")
    device = resolve_device(device)

    import subprocess

    command = _transkun_executable() + [
        str(audio_path),
        str(out_midi),
        "--device",
        device,
    ]
    segment_size = os.environ.get("TRANSKUN_SEGMENT_SIZE")
    if segment_size:
        command.extend(["--segmentSize", str(segment_size)])
    segment_hop = os.environ.get("TRANSKUN_SEGMENT_HOP")
    if segment_hop:
        command.extend(["--segmentHopSize", str(segment_hop)])
    result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0 or not Path(out_midi).exists():
        # Some versions do not accept --device; retry without it.
        retry = _transkun_executable() + [str(audio_path), str(out_midi)]
        result = subprocess.run(retry, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0 or not Path(out_midi).exists():
        raise MissingDependencyError(
            f"Transkun failed: {(result.stderr or result.stdout).strip()[-800:]}"
        )

    return _read_notes(out_midi), "transkun"


def _read_notes(path: Path) -> list[NoteEvent]:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(path))
    notes: list[NoteEvent] = []
    for instrument in midi.instruments:
        for note in instrument.notes:
            notes.append(
                NoteEvent(
                    start=note.start,
                    end=note.end,
                    pitch=note.pitch,
                    velocity=note.velocity,
                    confidence=1.0,
                )
            )
    return notes
