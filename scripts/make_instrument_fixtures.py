"""Generate deterministic solo-instrument fixtures for pipeline smoke tests.

Examples:
    python scripts/make_instrument_fixtures.py --out runtime/fixtures
    python scripts/make_instrument_fixtures.py --out runtime/fixtures --duration 6
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100


def _midi_hz(pitch: float) -> float:
    return 440.0 * 2.0 ** ((pitch - 69.0) / 12.0)


def _envelope(length: int, attack: float = 0.02, release: float = 0.15) -> np.ndarray:
    env = np.ones(length, dtype=np.float32)
    attack_n = max(1, int(attack * SR))
    release_n = max(1, int(release * SR))
    attack_n = min(attack_n, length)
    release_n = min(release_n, length)
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n, dtype=np.float32)
    env[-release_n:] *= np.linspace(1.0, 0.0, release_n, dtype=np.float32)
    return env


def _add_note(
    buffer: np.ndarray,
    start: float,
    duration: float,
    pitch: float,
    amplitude: float = 0.5,
    vibrato: float = 0.0,
    harmonics: tuple[float, ...] = (1.0,),
    decay: float = 0.0,
) -> None:
    start_n = int(max(0.0, start) * SR)
    length = int(max(0.05, duration) * SR)
    if start_n >= len(buffer):
        return
    length = min(length, len(buffer) - start_n)
    t = np.arange(length, dtype=np.float32) / SR
    phase = 2.0 * np.pi * _midi_hz(pitch) * t
    if vibrato:
        phase += vibrato * np.sin(2.0 * np.pi * 5.0 * t)
    wave = np.zeros(length, dtype=np.float32)
    for index, weight in enumerate(harmonics, start=1):
        wave += weight * np.sin(index * phase).astype(np.float32)
    env = _envelope(length)
    if decay:
        env *= np.exp(-t / max(0.05, decay)).astype(np.float32)
    buffer[start_n : start_n + length] += amplitude * env * wave


def erhu(out: Path) -> dict:
    duration = 8.0
    audio = np.zeros(int(duration * SR), dtype=np.float32)
    notes = [
        (0.0, 0.9, 62),
        (0.9, 0.9, 64),
        (1.8, 1.2, 66),
        (3.0, 1.0, 69),
        (4.0, 1.2, 71),
        (5.2, 1.4, 74),
        (6.6, 1.2, 69),
    ]
    for start, length, pitch in notes:
        _add_note(
            audio,
            start,
            length,
            pitch,
            amplitude=0.35,
            vibrato=0.22,
            harmonics=(1.0, 0.35, 0.18, 0.08),
            decay=1.4,
        )
    sf.write(out, audio, SR)
    return {"instrument": "erhu", "notes": notes, "duration": duration}


def guzheng(out: Path) -> dict:
    duration = 8.0
    audio = np.zeros(int(duration * SR), dtype=np.float32)
    notes = []
    for bar in range(4):
        base = bar * 2.0
        for index, pitch in enumerate((60, 64, 67, 72)):
            start = base + index * 0.18
            notes.append((start, 1.2, pitch))
            _add_note(
                audio,
                start,
                1.2,
                pitch,
                amplitude=0.32,
                harmonics=(1.0, 0.5, 0.3, 0.18, 0.1),
                decay=0.45,
            )
    sf.write(out, audio, SR)
    return {"instrument": "guzheng", "notes": notes, "duration": duration}


def synth_lead(out: Path) -> dict:
    duration = 8.0
    audio = np.zeros(int(duration * SR), dtype=np.float32)
    notes = [(0.0, 1.2, 57), (1.2, 1.2, 60), (2.4, 1.2, 64), (3.6, 1.2, 69)]
    for start, length, pitch in notes:
        _add_note(
            audio,
            start,
            length,
            pitch,
            amplitude=0.28,
            vibrato=0.05,
            harmonics=(1.0, 0.7, 0.5, 0.35, 0.25),
            decay=0.0,
        )
    sf.write(out, audio, SR)
    return {"instrument": "synth_lead", "notes": notes, "duration": duration}


def drums_808(out: Path) -> dict:
    duration = 4.0
    audio = np.zeros(int(duration * SR), dtype=np.float32)
    events = []
    for index in range(8):
        start = index * 0.5
        events.append((start, 0.18, 36, "kick"))
        length = int(0.18 * SR)
        t = np.arange(length, dtype=np.float32) / SR
        freq = 90.0 * np.exp(-t * 18.0) + 42.0
        audio[int(start * SR) : int(start * SR) + length] += (
            0.5 * np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 9)
        ).astype(np.float32)
        if index % 2 == 1:
            events.append((start, 0.12, 38, "snare"))
            length = int(0.12 * SR)
            t = np.arange(length, dtype=np.float32) / SR
            noise = np.random.default_rng(7).normal(0, 0.25, length).astype(np.float32)
            audio[int(start * SR) : int(start * SR) + length] += (
                noise * np.exp(-t * 24)
            )
        events.append((start, 0.05, 42, "closed_hat"))
        length = int(0.05 * SR)
        t = np.arange(length, dtype=np.float32) / SR
        noise = np.random.default_rng(index).normal(0, 0.12, length).astype(np.float32)
        audio[int(start * SR) : int(start * SR) + length] += (
            noise * np.exp(-t * 60)
        )
    sf.write(out, audio, SR)
    return {"instrument": "electronic_drums", "events": events, "duration": duration}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, builder in (
        ("erhu", erhu),
        ("guzheng", guzheng),
        ("synth_lead", synth_lead),
        ("drums_808", drums_808),
    ):
        path = out_dir / f"{name}.wav"
        manifest[name] = builder(path)
        print(f"{name}: {path}")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
