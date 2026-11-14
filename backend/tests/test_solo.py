from __future__ import annotations

import pretty_midi
import pytest

from app.instruments import REGISTRY
from app.models.adapters import solo
from app.models.adapters.common import note_events_to_midi
from app.pipeline.context import ProjectContext
from app.pipeline.stages.separate import SeparateStage
from app.pipeline.stages.transcribe import TranscribeStage
from app.types import NoteEvent


def _ctx(tmp_path, **kwargs) -> ProjectContext:
    return ProjectContext(
        project_id="solo",
        root=tmp_path / "project",
        source=tmp_path / "song.mp3",
        log=lambda *_: None,
        **kwargs,
    )


def _notes(count: int = 4, pitch: int = 60) -> list[NoteEvent]:
    return [
        NoteEvent(index * 0.5, index * 0.5 + 0.4, pitch + index % 3, 90, 0.8)
        for index in range(count)
    ]


def _write_wav(path, payload=b"RIFFfake"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_separate_solo_copies_source_to_instrument_stem(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, mode="solo", instrument_id="二胡")
    _write_wav(ctx.source_wav, b"RIFF-solo")

    def _fail(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("Demucs must not run in solo mode")

    monkeypatch.setattr(
        "app.pipeline.stages.separate.separate_to_stems", _fail
    )

    outputs, metrics = SeparateStage().execute(ctx, {})

    target = ctx.stem_path("erhu")
    assert outputs == {"solo": target}
    assert target.read_bytes() == b"RIFF-solo"
    assert metrics["mode"] == "solo"
    assert metrics["instrument_id"] == "erhu"
    assert metrics["stems"] == ["erhu"]


def test_transcribe_solo_uses_profile_adapter_and_skips_full_mix(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, mode="solo", instrument_id="erhu", preset="quality")
    _write_wav(ctx.stem_path("erhu"))
    ctx.write_json(ctx.analysis_path, {"bpm": 100.0})

    seen: dict = {}

    def _fake(audio_path, out_midi, profile, bpm=120.0, **kwargs):
        seen["profile"] = profile.id
        seen["bpm"] = bpm
        notes = _notes(3, 60)
        note_events_to_midi(notes, out_midi, program=profile.gm_program, bpm=bpm)
        return notes, "solo-pitch-fallback"

    monkeypatch.setattr(solo, "transcribe", _fake)
    # If solo mode ever tried the full mix this would run and be visible below.
    monkeypatch.setattr(
        "app.models.adapters.muscriptor.locate_weights",
        lambda: (_ for _ in ()).throw(AssertionError("full mix must not run")),
    )

    outputs, metrics = TranscribeStage().execute(ctx, {})

    assert seen["profile"] == "erhu"
    assert seen["bpm"] == pytest.approx(100.0)
    assert outputs == {"erhu": ctx.midi_model_dir / "erhu.mid"}
    assert outputs["erhu"].exists()
    assert metrics["erhu"]["instrument_id"] == "erhu"
    assert metrics["erhu"]["display_name"] == "Erhu"
    assert "muscriptor_mix" not in outputs


def test_transcribe_full_mode_picks_up_catalog_extra_stem(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    _write_wav(ctx.stem_path("violin"))
    _write_wav(ctx.stem_path("mystery"))
    ctx.write_json(ctx.analysis_path, {"bpm": 120.0})

    calls: list[str] = []

    def _fake(audio_path, out_midi, profile, bpm=120.0, **kwargs):
        calls.append(profile.id)
        notes = _notes(2, 64)
        note_events_to_midi(notes, out_midi, program=profile.gm_program, bpm=bpm)
        return notes, "solo-fake"

    monkeypatch.setattr(solo, "transcribe", _fake)

    outputs, metrics = TranscribeStage().execute(ctx, {})

    # violin.wav resolves in the catalog; mystery.wav does not and is ignored.
    assert calls == ["violin"]
    assert list(outputs) == ["violin"]
    assert metrics["violin"]["instrument_id"] == "violin"


def test_solo_monophonic_profile_uses_pitch_with_catalog_range(tmp_path, monkeypatch):
    profile = REGISTRY.get("erhu")
    assert profile is not None and profile.monophonic
    seen: dict = {}

    def _fake_pitch(audio_path, out_midi, program=0, bpm=120.0, fmin=65.0, fmax=1200.0, is_drum=False):
        seen.update(program=program, fmin=fmin, fmax=fmax)
        return [
            NoteEvent(0.0, 0.5, 60, 90, 0.8),
            NoteEvent(0.5, 1.0, 30, 90, 0.8),  # below the erhu range
        ], "pitch-fallback"

    monkeypatch.setattr(solo.pitch, "transcribe", _fake_pitch)

    out = tmp_path / "erhu.mid"
    notes, model = solo.transcribe(tmp_path / "in.wav", out, profile, bpm=90.0)

    assert model == "solo-pitch-fallback"
    assert seen["program"] == profile.gm_program
    assert seen["fmin"] == pytest.approx(195.99, rel=1e-3)
    assert seen["fmax"] == pytest.approx(2637.02, rel=1e-3)
    assert [note.pitch for note in notes] == [60]
    written = pretty_midi.PrettyMIDI(str(out))
    assert written.instruments[0].program == profile.gm_program


def test_solo_polyphonic_profile_caps_polyphony(tmp_path, monkeypatch):
    profile = REGISTRY.get("guqin")  # non-monophonic, max_polyphony 4
    assert profile is not None and profile.max_polyphony == 4
    seen: dict = {}

    def _fake_basic_pitch(audio_path, out_midi, program=0, min_frequency=0.0, max_frequency=0.0, min_note_length_ms=58.0, onset_threshold=0.5, frame_threshold=0.3, bpm=120.0):
        seen.update(program=program, low=min_frequency, high=max_frequency)
        return [
            NoteEvent(0.0, 0.5, pitch, 60 + index * 10, 0.9)
            for index, pitch in enumerate([60, 62, 64, 65, 67, 69])
        ], "basic-pitch"

    monkeypatch.setattr(solo.basic_pitch, "transcribe", _fake_basic_pitch)

    notes, model = solo.transcribe(tmp_path / "in.wav", tmp_path / "guqin.mid", profile)

    assert model == "solo-basic-pitch"
    assert seen["program"] == profile.gm_program
    assert seen["low"] == pytest.approx(65.41, rel=1e-3)  # C2 = range_low 36
    assert len(notes) == profile.max_polyphony


def test_solo_percussion_profile_uses_drum_transcriber(tmp_path, monkeypatch):
    profile = REGISTRY.get("tabla")
    assert profile is not None and profile.notation == "percussion"

    def _fake_drums(audio_path, out_midi, bpm=120.0):
        return [
            NoteEvent(0.0, 0.1, 36, 110, 1.0),
            NoteEvent(0.5, 0.6, 38, 100, 1.0),
        ], "adtof"

    monkeypatch.setattr(solo.drums, "transcribe", _fake_drums)
    monkeypatch.setattr(
        solo.basic_pitch,
        "transcribe",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("pitched path used")),
    )

    out = tmp_path / "tabla.mid"
    notes, model = solo.transcribe(tmp_path / "in.wav", out, profile)

    assert model == "solo-adtof"
    assert len(notes) == 2
    written = pretty_midi.PrettyMIDI(str(out))
    assert written.instruments[0].is_drum is True
    assert written.instruments[0].program == 0


def test_solo_voice_profile_prefers_vocal_path(tmp_path, monkeypatch):
    profile = REGISTRY.get("vocals")

    def _fake_vocals(audio_path, out_midi, bpm=120.0, **kwargs):
        return [NoteEvent(0.0, 0.6, 64, 90, 0.9)], "game+melody"

    monkeypatch.setattr(solo.vocals, "transcribe", _fake_vocals)

    out = tmp_path / "vocals.mid"
    notes, model = solo.transcribe(tmp_path / "in.wav", out, profile)

    assert model == "solo-game+melody"
    assert [note.pitch for note in notes] == [64]


def test_solo_effect_profile_is_skipped(tmp_path):
    profile = REGISTRY.get("fx")
    assert profile is not None and profile.notation == "none"

    notes, model = solo.transcribe(tmp_path / "in.wav", tmp_path / "fx.mid", profile)

    assert notes == []
    assert model == "skipped-fx"
    assert not (tmp_path / "fx.mid").exists()
