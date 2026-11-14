"""Generate deterministic synthetic test songs with known stems.

These are not a substitute for real music, but they give the pipeline a
reproducible input with ground-truth stems for smoke tests and SDR checks.

Usage:
    python scripts/make_test_audio.py --out runtime/data/test
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
RNG = np.random.default_rng(7)


def adsr(length: int, attack: float = 0.01, decay: float = 0.12, sustain: float = 0.65, release: float = 0.2) -> np.ndarray:
    env = np.ones(length, dtype=np.float32) * sustain
    a = min(int(attack * SR), length)
    d = min(int(decay * SR), max(0, length - a))
    r = min(int(release * SR), max(0, length - a - d))
    if a:
        env[:a] = np.linspace(0, 1, a, dtype=np.float32)
    if d:
        env[a : a + d] = np.linspace(1, sustain, d, dtype=np.float32)
    if r:
        env[length - r :] = np.linspace(sustain, 0, r, dtype=np.float32)
    return env


def piano_note(freq: float, duration: float) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    signal = np.zeros(length, dtype=np.float32)
    for harmonic in range(1, 9):
        amplitude = 1.0 / (harmonic**1.6)
        signal += amplitude * np.sin(2 * np.pi * freq * harmonic * t)
    signal *= np.exp(-2.2 * t / max(duration, 0.01))
    return (signal * adsr(length, 0.005, 0.05, 0.8, 0.15)).astype(np.float32)


def bass_note(freq: float, duration: float) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    signal = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t)
    signal *= np.exp(-1.4 * t / max(duration, 0.01))
    return (signal * adsr(length, 0.005, 0.05, 0.8, 0.1)).astype(np.float32)


def kick(duration: float = 0.22) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    freq = 110 * np.exp(-18 * t) + 45
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return (np.sin(phase) * np.exp(-16 * t)).astype(np.float32)


def snare(duration: float = 0.18) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    noise = RNG.normal(0, 1, length).astype(np.float32)
    tone = np.sin(2 * np.pi * 190 * t).astype(np.float32)
    return ((0.7 * noise + 0.3 * tone) * np.exp(-24 * t)).astype(np.float32)


def hihat(duration: float = 0.08) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    noise = RNG.normal(0, 1, length).astype(np.float32)
    # crude high-pass: first difference
    noise = np.diff(noise, prepend=0.0)
    return (noise * np.exp(-60 * t)).astype(np.float32)


def guitar_note(freq: float, duration: float) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    signal = np.zeros(length, dtype=np.float32)
    for harmonic in range(1, 12):
        signal += (1.0 / harmonic) * np.sin(2 * np.pi * freq * harmonic * t)
    signal = np.tanh(2.2 * signal)
    return (signal * adsr(length, 0.005, 0.08, 0.7, 0.12)).astype(np.float32)


def vocal_note(freq: float, duration: float) -> np.ndarray:
    length = int(duration * SR)
    t = np.arange(length, dtype=np.float32) / SR
    vibrato = 1 + 0.012 * np.sin(2 * np.pi * 5.2 * t)
    phase = 2 * np.pi * np.cumsum(freq * vibrato) / SR
    signal = (
        0.6 * np.sin(phase)
        + 0.25 * np.sin(2 * phase)
        + 0.1 * np.sin(3 * phase)
        + 0.05 * np.sin(5 * phase)
    )
    return (signal * adsr(length, 0.03, 0.1, 0.75, 0.15)).astype(np.float32)


def midi_to_freq(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def add_at(buffer: np.ndarray, signal: np.ndarray, start: float, gain: float = 1.0) -> None:
    start_index = int(start * SR)
    end_index = min(len(buffer), start_index + len(signal))
    if end_index <= start_index:
        return
    buffer[start_index:end_index] += signal[: end_index - start_index] * gain


def make_pop(path: Path, duration: float = 32.0) -> dict[str, np.ndarray]:
    samples = int(duration * SR)
    stems = {
        "vocals": np.zeros(samples, dtype=np.float32),
        "drums": np.zeros(samples, dtype=np.float32),
        "bass": np.zeros(samples, dtype=np.float32),
        "guitar": np.zeros(samples, dtype=np.float32),
        "piano": np.zeros(samples, dtype=np.float32),
    }
    bpm = 96
    beat = 60.0 / bpm
    bar = 4 * beat

    progression = [
        ([60, 64, 67], 36),  # C
        ([55, 59, 62], 31),  # G
        ([57, 60, 64], 33),  # Am
        ([53, 57, 60], 29),  # F
    ]
    melody = [72, 74, 76, 79, 76, 74, 72, 67, 69, 72, 74, 76, 72, 71, 69, 67]

    for bar_index in range(int(duration / bar) + 1):
        start = bar_index * bar
        if start >= duration:
            break
        chord, root = progression[bar_index % len(progression)]

        # Piano: block chord on beat 1, arpeggio on beats 2-4.
        for note in chord:
            add_at(stems["piano"], piano_note(midi_to_freq(note), beat * 1.8), start, 0.18)
        for offset, note in zip((1.0, 2.0, 3.0), chord[::-1]):
            add_at(stems["piano"], piano_note(midi_to_freq(note + 12), beat * 0.5), start + offset * beat, 0.12)

        # Bass: root on 1 and 3.
        add_at(stems["bass"], bass_note(midi_to_freq(root), beat * 0.9), start, 0.5)
        add_at(stems["bass"], bass_note(midi_to_freq(root), beat * 0.9), start + 2 * beat, 0.45)

        # Drums: kick 1/3, snare 2/4, hats eighths.
        for offset in (0.0, 2.0):
            add_at(stems["drums"], kick(), start + offset * beat, 0.8)
        for offset in (1.0, 3.0):
            add_at(stems["drums"], snare(), start + offset * beat, 0.55)
        for eighth in range(8):
            add_at(stems["drums"], hihat(), start + eighth * beat / 2, 0.25)

        # Guitar: plucked chord on beats 2 and 4.
        for offset in (1.0, 3.0):
            for note in chord[:3]:
                add_at(stems["guitar"], guitar_note(midi_to_freq(note + 12), beat * 0.45), start + offset * beat, 0.08)

        # Vocal: two notes per bar from the melody.
        for index, offset in enumerate((0.5, 2.5)):
            note = melody[(bar_index * 2 + index) % len(melody)]
            add_at(stems["vocals"], vocal_note(midi_to_freq(note), beat * 1.1), start + offset * beat, 0.28)

    return _write_stems(path, stems)


def make_piano(path: Path, duration: float = 24.0) -> dict[str, np.ndarray]:
    samples = int(duration * SR)
    stems = {"piano": np.zeros(samples, dtype=np.float32)}
    bpm = 72
    beat = 60.0 / bpm

    chords = [
        [60, 64, 67, 72],
        [57, 60, 64, 69],
        [53, 57, 60, 65],
        [55, 59, 62, 67],
    ]
    for bar_index in range(int(duration / (4 * beat)) + 1):
        start = bar_index * 4 * beat
        if start >= duration:
            break
        chord = chords[bar_index % len(chords)]
        for note in chord:
            add_at(stems["piano"], piano_note(midi_to_freq(note), beat * 3.6), start, 0.2)
        for index, note in enumerate(chord):
            add_at(stems["piano"], piano_note(midi_to_freq(note + 12), beat * 0.8), start + (index + 1) * beat, 0.14)
        add_at(stems["piano"], piano_note(midi_to_freq(chord[0] - 12), beat * 1.5), start + 2.5 * beat, 0.25)

    return _write_stems(path, stems)


def make_rock(path: Path, duration: float = 28.0) -> dict[str, np.ndarray]:
    samples = int(duration * SR)
    stems = {
        "drums": np.zeros(samples, dtype=np.float32),
        "bass": np.zeros(samples, dtype=np.float32),
        "guitar": np.zeros(samples, dtype=np.float32),
        "vocals": np.zeros(samples, dtype=np.float32),
    }
    bpm = 120
    beat = 60.0 / bpm
    bar = 4 * beat

    riff = [40, 40, 43, 45, 40, 40, 47, 45]
    for bar_index in range(int(duration / bar) + 1):
        start = bar_index * bar
        if start >= duration:
            break
        for index, note in enumerate(riff):
            offset = index * beat / 2
            add_at(stems["guitar"], guitar_note(midi_to_freq(note + 12), beat * 0.4), start + offset, 0.16)
            if index % 2 == 0:
                add_at(stems["bass"], bass_note(midi_to_freq(note - 12), beat * 0.4), start + offset, 0.45)
        for offset in (0.0, 2.0):
            add_at(stems["drums"], kick(), start + offset * beat, 0.9)
        for offset in (1.0, 3.0):
            add_at(stems["drums"], snare(), start + offset * beat, 0.6)
        for eighth in range(8):
            add_at(stems["drums"], hihat(), start + eighth * beat / 2, 0.3)
        add_at(stems["vocals"], vocal_note(midi_to_freq(64), beat * 1.8), start + beat, 0.2)
        add_at(stems["vocals"], vocal_note(midi_to_freq(67), beat * 1.2), start + 3 * beat, 0.2)

    return _write_stems(path, stems)


def _write_stems(path: Path, stems: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    peak = max(float(np.max(np.abs(stem))) for stem in stems.values()) or 1.0
    mix = np.zeros_like(next(iter(stems.values())))
    for stem in stems.values():
        mix += stem
    mix_peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / mix_peak * 0.9

    sf.write(str(path), np.stack([mix, mix], axis=1), SR, subtype="PCM_16")

    stem_dir = path.with_name(path.stem + "_stems")
    stem_dir.mkdir(parents=True, exist_ok=True)
    for name, signal in stems.items():
        normalized = signal / peak * 0.8
        sf.write(str(stem_dir / f"{name}.wav"), np.stack([normalized, normalized], axis=1), SR, subtype="PCM_16")

    return stems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/test")
    args = parser.parse_args()
    out = Path(args.out)
    make_pop(out / "synth-pop.wav")
    make_piano(out / "synth-piano.wav")
    make_rock(out / "synth-rock.wav")
    print(f"wrote test audio to {out.resolve()}")


if __name__ == "__main__":
    main()
