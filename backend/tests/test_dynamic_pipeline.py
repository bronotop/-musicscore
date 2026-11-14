from __future__ import annotations

import json
from pathlib import Path

import pretty_midi
import pytest

from app.instruments import REGISTRY
from app.models.adapters import solo
from app.pipeline.context import ProjectContext
from app.pipeline.stages.assemble import AssembleStage
from app.pipeline.stages.separate import SeparateStage
from app.types import NoteEvent


def _ctx(root: Path, mode: str = "full", instrument_id: str | None = None) -> ProjectContext:
    return ProjectContext(
        project_id="test",
        root=root,
        source=root / "source.wav",
        mode=mode,
        instrument_id=instrument_id,
        log=lambda *_: None,
    )


def _write_midi(path: Path, notes, program: int = 0, name: str = "") -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=program, name=name)
    for start, end, pitch in notes:
        instrument.notes.append(pretty_midi.Note(100, pitch, start, end))
    midi.instruments.append(instrument)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def test_solo_separation_copies_source(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.wav").write_bytes(b"RIFFxxxxWAVE")
    (root / "stems").mkdir()
    ctx = _ctx(root, mode="solo", instrument_id="erhu")
    outputs, metrics = SeparateStage().execute(ctx, {})
    assert metrics["mode"] == "solo"
    assert metrics["instrument_id"] == "erhu"
    assert (root / "stems" / "erhu.wav").read_bytes() == (root / "source.wav").read_bytes()


def test_solo_monophonic_writes_catalog_program(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    audio = root / "erhu.wav"
    audio.write_bytes(b"RIFFxxxxWAVE")
    out = root / "erhu.mid"

    def fake_pitch(audio_path, out_path, **kwargs):
        return [NoteEvent(0.0, 0.5, 62, 90, 0.9), NoteEvent(0.6, 1.0, 64, 90, 0.9)], "fake-pitch"

    monkeypatch.setattr(solo.pitch, "transcribe", fake_pitch)
    notes, model = solo.transcribe(audio, out, REGISTRY.resolve("erhu"), bpm=120)
    assert len(notes) == 2 and model == "solo-fake-pitch"
    midi = pretty_midi.PrettyMIDI(str(out))
    assert midi.instruments[0].program == 110
    assert midi.instruments[0].name == "erhu"


def test_dynamic_assemble_writes_track_metadata(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    ctx = _ctx(root)
    ctx.write_json(
        ctx.analysis_path,
        {"bpm": 120.0, "beats": [i * 0.5 for i in range(9)], "duration": 4.0},
    )
    _write_midi(ctx.midi_model_dir / "erhu.mid", [(0.0, 0.5, 62)], program=110, name="erhu")
    _write_midi(ctx.midi_model_dir / "guzheng.mid", [(0.0, 0.5, 60), (0.5, 1.0, 64)], program=107, name="guzheng")
    _write_midi(ctx.midi_model_dir / "fx.mid", [(0.0, 0.2, 60)], program=99, name="fx")
    (ctx.stems_dir / "erhu.wav").write_bytes(b"RIFFxxxxWAVE")
    outputs, metrics = AssembleStage().execute(ctx, {})
    tracks = json.loads((ctx.midi_final_dir / "tracks.json").read_text(encoding="utf-8"))["tracks"]
    by_stem = {track["stem"]: track for track in tracks}
    assert "fx" not in by_stem
    assert by_stem["erhu"]["instrument_id"] == "erhu"
    assert by_stem["erhu"]["program"] == 110
    assert by_stem["erhu"]["midi"] == "midi/final/erhu.mid"
    assert by_stem["erhu"]["audio"] == "stems/erhu.wav"
    assert by_stem["guzheng"]["audio"] is None
    assert by_stem["guzheng"]["clef"] == "treble"
    assert (ctx.midi_final_dir / "erhu.mid").exists()
    assert (ctx.midi_final_dir / "guzheng.mid").exists()
    full = pretty_midi.PrettyMIDI(str(ctx.midi_final_dir / "full.mid"))
    assert {instrument.name for instrument in full.instruments} == {"erhu", "guzheng"}
    assert metrics["tracks"] == 2
