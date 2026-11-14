from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.models.adapters import game, melody
from app.models.adapters import vocals as vocals_adapter
from app.types import NoteEvent


def _polyphony(notes: list[NoteEvent], tolerance: float = 0.02) -> tuple[int, float]:
    """Same simultaneity metric as scripts/quality_report.py."""
    if not notes:
        return 0, 0.0
    events: list[tuple[float, int]] = []
    for note in notes:
        events.append((note.start, 1))
        events.append((max(note.start + tolerance, note.end - tolerance), -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    active = maximum = 0
    overlapped = 0
    previous_time = None
    previous_active = 0
    for time, delta in events:
        if previous_time is not None and previous_active > 1:
            overlapped += time - previous_time
        active += delta
        maximum = max(maximum, active)
        previous_time = time
        previous_active = active
    span = max(note.end for note in notes)
    return maximum, (overlapped / span if span > 0 else 0.0)


def _track(
    end: float = 1.2,
    split: float = 0.6,
    first_pitch: float = 60.0,
    second_pitch: float = 64.0,
) -> melody.PitchTrack:
    times = np.arange(0.0, end, 0.01)
    midi = np.where(times < split, first_pitch, second_pitch)
    return melody.PitchTrack(
        times=times,
        midi=midi,
        confidence=np.full_like(times, 0.9),
    )


def test_select_melody_removes_overtone_and_keeps_one_line():
    notes = [
        NoteEvent(0.0, 0.5, 60, velocity=60, confidence=0.5),
        NoteEvent(0.0, 0.5, 72, velocity=110, confidence=0.9),  # overtone
        NoteEvent(0.6, 1.0, 64, velocity=100, confidence=0.8),
        NoteEvent(0.7, 1.1, 60, velocity=40, confidence=0.3),
    ]
    result = melody.select_melody(notes, track=_track())
    pitches = [note.pitch for note in result]
    assert 72 not in pitches
    assert pitches == [60, 64]
    maximum, overlap = _polyphony(result)
    assert maximum == 1
    assert overlap == 0.0


def test_select_melody_merges_vibrato_fragments():
    notes = [
        NoteEvent(0.0, 0.20, 60, velocity=80, confidence=0.6),
        NoteEvent(0.23, 0.40, 60, velocity=82, confidence=0.7),
    ]
    result = melody.select_melody(notes)
    assert len(result) == 1
    assert result[0].pitch == 60
    assert result[0].start == pytest.approx(0.0)
    assert result[0].end == pytest.approx(0.40)
    assert result[0].confidence == pytest.approx(0.7)


def test_select_melody_keeps_stronger_overlap_and_drops_head_fragment():
    notes = [
        NoteEvent(0.0, 0.5, 60, velocity=60, confidence=0.6),
        NoteEvent(0.1, 0.4, 64, velocity=100, confidence=0.9),
    ]
    result = melody.select_melody(notes)
    assert [note.pitch for note in result] == [64]
    assert _polyphony(result)[0] == 1


def test_select_melody_drops_short_fragment():
    notes = [
        NoteEvent(0.0, 0.30, 60, velocity=80, confidence=0.8),
        NoteEvent(0.31, 0.34, 62, velocity=80, confidence=0.8),
        NoteEvent(0.50, 0.80, 64, velocity=80, confidence=0.8),
    ]
    result = melody.select_melody(notes)
    assert 62 not in [note.pitch for note in result]
    assert [note.pitch for note in result] == [60, 64]
    assert _polyphony(result)[0] == 1


def test_select_melody_leaves_gap_between_adjacent_notes():
    notes = [
        NoteEvent(0.0, 0.4, 60, velocity=80, confidence=0.8),
        NoteEvent(0.4, 0.8, 64, velocity=80, confidence=0.8),
    ]
    result = melody.select_melody(notes)
    assert len(result) == 2
    assert result[0].end < result[1].start
    assert _polyphony(result)[0] == 1


def test_select_melody_drops_short_implausible_leap():
    notes = [
        NoteEvent(0.0, 0.40, 60, velocity=80, confidence=0.8),
        NoteEvent(0.50, 0.60, 84, velocity=80, confidence=0.8),
        NoteEvent(0.70, 1.10, 62, velocity=80, confidence=0.8),
    ]
    result = melody.select_melody(notes)
    assert 84 not in [note.pitch for note in result]
    assert [note.pitch for note in result] == [60, 62]


def test_melody_config_reads_environment(monkeypatch):
    monkeypatch.setenv("VOCAL_MELODY_MIN_NOTE_MS", "120")
    monkeypatch.setenv("VOCAL_MELODY_MIN_CONFIDENCE", "0.35")
    monkeypatch.setenv("VOCAL_MELODY_MAX_LEAP", "7")
    monkeypatch.setenv("VOCAL_MELODY_USE_F0", "0")
    config = melody.MelodyConfig.from_env()
    assert config.min_note_ms == 120.0
    assert config.min_confidence == 0.35
    assert config.max_leap == 7
    assert config.use_pitch_track is False


def test_locate_model_requires_complete_export(tmp_path, monkeypatch):
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "config.json").write_text("{}", encoding="utf-8")
    complete = tmp_path / "GAME-test-onnx"
    complete.mkdir()
    for name in game.REQUIRED_FILES:
        (complete / name).write_text("", encoding="utf-8")

    monkeypatch.setattr(game, "_candidate_dirs", lambda: [incomplete])
    assert game.locate_model() is None

    monkeypatch.setattr(game, "_candidate_dirs", lambda: [incomplete, complete])
    assert game.locate_model() == complete
    assert game.available() is True


def test_transcribe_silence_gate_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCAL_MELODY_SILENCE_RMS", "0.001")
    monkeypatch.setattr(game, "locate_model", lambda: None)
    monkeypatch.setattr(melody, "audio_duration", lambda path: 5.0)
    monkeypatch.setattr(melody, "audio_rms", lambda path: 0.00001)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Basic Pitch should not run")),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "silent.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert notes == []
    assert model == "silence-gate"
    assert (tmp_path / "vocals.mid").exists()


def test_transcribe_falls_back_without_game_model(tmp_path, monkeypatch):
    monkeypatch.delenv("VOCAL_MELODY_MODE", raising=False)
    monkeypatch.setattr(game, "locate_model", lambda: None)
    monkeypatch.setattr(melody, "audio_duration", lambda path: 1.0)
    monkeypatch.setattr(melody, "track_f0", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (
            [NoteEvent(0.0, 0.5, 60, velocity=80, confidence=0.8)],
            "basic-pitch",
        ),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert len(notes) == 1
    assert model == "basic-pitch+melody-no-f0"
    assert (tmp_path / "vocals.mid").exists()


def test_transcribe_falls_back_when_game_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("VOCAL_MELODY_MODE", raising=False)
    monkeypatch.setattr(game, "locate_model", lambda: tmp_path / "fake-game")
    monkeypatch.setattr(
        game,
        "transcribe",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(melody, "audio_duration", lambda path: 1.0)
    monkeypatch.setattr(melody, "track_f0", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (
            [NoteEvent(0.0, 0.5, 60, velocity=80, confidence=0.8)],
            "basic-pitch",
        ),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert len(notes) == 1
    assert model == "game-failed->basic-pitch+melody-no-f0"


def test_transcribe_falls_back_when_game_is_sparse(tmp_path, monkeypatch):
    monkeypatch.delenv("VOCAL_MELODY_MODE", raising=False)
    monkeypatch.setattr(game, "locate_model", lambda: tmp_path / "fake-game")
    monkeypatch.setattr(
        game,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(0.0, 1.0, 60, velocity=90, confidence=0.85),
                NoteEvent(1.0, 2.0, 62, velocity=90, confidence=0.85),
            ],
            "game-test",
        ),
    )
    monkeypatch.setattr(melody, "audio_duration", lambda path: 10.0)
    monkeypatch.setattr(melody, "track_f0", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(index * 0.1, index * 0.1 + 0.08, 60 + index, confidence=0.8)
                for index in range(20)
            ],
            "basic-pitch",
        ),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert notes
    assert model == "game-sparse->basic-pitch+melody-no-f0"


def test_transcribe_auto_uses_dense_game_result(tmp_path, monkeypatch):
    monkeypatch.delenv("VOCAL_MELODY_MODE", raising=False)
    monkeypatch.setattr(game, "locate_model", lambda: tmp_path / "fake-game")
    monkeypatch.setattr(
        game,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(index * 1.5, index * 1.5 + 1.0, 60 + index, confidence=0.85)
                for index in range(6)
            ],
            "game-test",
        ),
    )
    monkeypatch.setattr(melody, "audio_duration", lambda path: 10.0)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Basic Pitch should not run")),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert notes
    assert model == "game-test+melody"


def test_transcribe_gate_uses_cleaned_game_notes(tmp_path, monkeypatch):
    """Regression: raw GAME regions can look dense while cleanup keeps one note."""
    monkeypatch.delenv("VOCAL_MELODY_MODE", raising=False)
    monkeypatch.setattr(game, "locate_model", lambda: tmp_path / "fake-game")
    monkeypatch.setattr(
        game,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(0.0, 1.0, 60 + index, confidence=0.85)
                for index in range(10)
            ],
            "game-test",
        ),
    )
    monkeypatch.setattr(melody, "audio_duration", lambda path: 10.0)
    monkeypatch.setattr(melody, "track_f0", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(index * 0.1, index * 0.1 + 0.08, 60 + index, confidence=0.8)
                for index in range(20)
            ],
            "basic-pitch",
        ),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert notes
    assert model == "game-sparse->basic-pitch+melody-no-f0"


def test_transcribe_forced_game_mode_uses_game(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCAL_MELODY_MODE", "game")
    monkeypatch.setattr(game, "locate_model", lambda: tmp_path / "fake-game")
    monkeypatch.setattr(
        game,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(0.0, 1.0, 60, velocity=90, confidence=0.85),
                NoteEvent(1.0, 2.0, 62, velocity=90, confidence=0.85),
            ],
            "game-test",
        ),
    )
    monkeypatch.setattr(melody, "audio_duration", lambda path: 2.0)
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Basic Pitch should not run")),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert len(notes) == 2
    assert model == "game-test+melody"


def test_basic_mode_preserves_previous_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("VOCAL_MELODY_MODE", "basic")
    monkeypatch.setattr(game, "locate_model", lambda: None)
    monkeypatch.setattr(melody, "audio_duration", lambda path: 1.0)
    monkeypatch.setattr(
        melody,
        "track_f0",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("f0 should not run")),
    )
    monkeypatch.setattr(
        vocals_adapter.basic_pitch,
        "transcribe",
        lambda *args, **kwargs: (
            [
                NoteEvent(0.0, 0.6, 60, velocity=80, confidence=0.8),
                NoteEvent(0.1, 0.5, 64, velocity=100, confidence=0.9),
            ],
            "basic-pitch",
        ),
    )

    notes, model = vocals_adapter.transcribe(
        tmp_path / "vocals.wav",
        tmp_path / "vocals.mid",
        bpm=120.0,
    )
    assert model == "basic-pitch+mono"
    assert 64 in [note.pitch for note in notes]
