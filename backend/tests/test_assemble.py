from __future__ import annotations

import json

import pretty_midi
import pytest

from app.pipeline.context import ProjectContext
from app.pipeline.stages.assemble import AssembleStage


def _write_midi(path, notes, program=0, is_drum=False):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=program, is_drum=is_drum)
    for start, end, pitch in notes:
        instrument.notes.append(pretty_midi.Note(100, pitch, start, end))
    midi.instruments.append(instrument)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def _write_midi_with_confidence(path, rows, program=0):
    """Write model MIDI plus its confidence sidecar.

    ``rows`` are ``(start, end, pitch, velocity, confidence)`` tuples.
    """
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=program)
    for start, end, pitch, velocity, _ in rows:
        instrument.notes.append(pretty_midi.Note(velocity, pitch, start, end))
    midi.instruments.append(instrument)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    payload = {
        "notes": [
            {
                "start": start,
                "end": end,
                "pitch": pitch,
                "confidence": confidence,
            }
            for start, end, pitch, _, confidence in rows
        ]
    }
    path.with_name(f"{path.stem}.confidence.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_assemble_quantizes_and_merges(tmp_path):
    ctx = ProjectContext(
        project_id="test",
        root=tmp_path / "project",
        source=tmp_path / "song.mp3",
        log=lambda *_: None,
    )
    ctx.write_json(
        ctx.analysis_path,
        {
            "bpm": 120.0,
            "beats": [i * 0.5 for i in range(9)],
            "downbeats": [0.0, 2.0, 4.0],
            "time_signature": "4/4",
            "duration": 4.0,
        },
    )
    _write_midi(ctx.midi_model_dir / "piano.mid", [(0.16, 0.36, 60)], program=0)
    _write_midi(ctx.midi_model_dir / "drums.mid", [(0.01, 0.05, 36)], is_drum=True)

    stage = AssembleStage()
    outputs, metrics = stage.execute(ctx, {})

    assert outputs["full"].exists()
    assert metrics["tracks"] == 2

    full = pretty_midi.PrettyMIDI(str(outputs["full"]))
    assert len(full.instruments) == 2

    piano = next(inst for inst in full.instruments if not inst.is_drum)
    assert piano.notes[0].pitch == 60
    assert piano.notes[0].start == pytest.approx(0.125)

    drums = next(inst for inst in full.instruments if inst.is_drum)
    assert drums.notes[0].pitch == 36
    assert drums.notes[0].start == pytest.approx(0.0, abs=1e-6)


def test_assemble_filters_muscriptor_noise(tmp_path):
    ctx = ProjectContext(
        project_id="mix",
        root=tmp_path / "mix",
        source=tmp_path / "song.mp3",
        log=lambda *_: None,
    )
    ctx.write_json(
        ctx.analysis_path,
        {
            "bpm": 120.0,
            "beats": [i * 0.5 for i in range(9)],
            "downbeats": [0.0, 2.0, 4.0],
            "time_signature": "4/4",
            "duration": 4.0,
        },
    )
    guitar_notes = [
        (0.1 + index * 0.5, 0.4 + index * 0.5, pitch)
        for index, pitch in enumerate([60, 64, 67, 71])
    ]
    _write_midi(ctx.midi_model_dir / "guitar.mid", guitar_notes, program=25)

    mix = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    specs = [
        ("muscriptor_trumpet", 56, [(0.1 + i * 0.5, 0.4 + i * 0.5, p) for i, p in enumerate([72, 74, 76, 79])]),
        ("muscriptor_trombone", 57, guitar_notes),
        ("muscriptor_tuba", 58, [(0.1, 0.3, 40), (0.6, 0.8, 41)]),
        (
            "muscriptor_program 99",
            99,
            [(0.1 + i * 0.4, 0.3 + i * 0.4, 60) for i in range(5)],
        ),
        ("muscriptor_core_piano", 0, [(0.1, 0.3, 60), (0.6, 0.8, 62)]),
    ]
    for name, program, notes in specs:
        instrument = pretty_midi.Instrument(program=program, name=name)
        for start, end, pitch in notes:
            instrument.notes.append(pretty_midi.Note(100, pitch, start, end))
        mix.instruments.append(instrument)
    ctx.midi_model_dir.mkdir(parents=True, exist_ok=True)
    mix.write(str(ctx.midi_model_dir / "muscriptor_mix.mid"))

    stage = AssembleStage()
    outputs, metrics = stage.execute(ctx, {})

    names = [track["stem"] for track in metrics["per_track"]]
    assert "muscriptor_trumpet" in names
    assert "muscriptor_trombone" not in names
    assert "muscriptor_tuba" not in names
    assert "muscriptor_program 99" not in names
    assert "muscriptor_core_piano" not in names
    reasons = [item["reason"] for item in metrics["muscriptor_filtered"]]
    assert any("duplicates core" in reason for reason in reasons)
    assert any("only 2 notes" in reason for reason in reasons)
    assert any("unknown sparse program" in reason for reason in reasons)

    confidence = ctx.read_json(ctx.midi_final_dir / "confidence.json", {})
    confidence_tracks = {track["stem"] for track in confidence.get("tracks", [])}
    assert {"guitar", "muscriptor_trumpet"} <= confidence_tracks


def test_assemble_applies_fusion_and_reports_metrics(tmp_path):
    ctx = ProjectContext(
        project_id="fusion",
        root=tmp_path / "fusion",
        source=tmp_path / "song.mp3",
        log=lambda *_: None,
    )
    ctx.write_json(
        ctx.analysis_path,
        {
            "bpm": 120.0,
            "beats": [i * 0.5 for i in range(9)],
            "downbeats": [0.0, 2.0, 4.0],
            "time_signature": "4/4",
            "duration": 4.0,
        },
    )
    rows = [
        (0.10, 0.40, 60, 100, 0.20),  # low confidence, dropped
        (0.10, 0.40, 62, 100, 0.90),
        (0.10, 0.40, 64, 100, 0.90),
        (0.10, 0.40, 65, 100, 0.90),
        (0.10, 0.40, 67, 100, 0.90),
        (0.60, 0.64, 72, 100, 0.35),  # short and uncertain, dropped
        (0.80, 0.84, 74, 100, 0.90),  # short but confident, kept
    ]
    _write_midi_with_confidence(ctx.midi_model_dir / "guitar.mid", rows, program=25)

    stage = AssembleStage()
    outputs, metrics = stage.execute(ctx, {})

    stats = next(
        track for track in metrics["fusion"]["tracks"] if track["stem"] == "guitar"
    )
    assert stats["before"] == 7
    assert stats["after"] == 5
    assert stats["removed"]["low_confidence"] == 1
    assert stats["removed"]["short_fragment"] == 1
    assert metrics["fusion"]["notes_before"] == 7
    assert metrics["fusion"]["notes_after"] == 5

    guitar = pretty_midi.PrettyMIDI(str(outputs["guitar"]))
    pitches = [note.pitch for instrument in guitar.instruments for note in instrument.notes]
    assert set(pitches) == {62, 64, 65, 67, 74}
    assert metrics["notes"] == 5


def test_assemble_raises_without_midi(tmp_path):
    ctx = ProjectContext(
        project_id="empty",
        root=tmp_path / "empty",
        source=tmp_path / "song.mp3",
        log=lambda *_: None,
    )
    ctx.write_json(ctx.analysis_path, {"bpm": 120.0, "beats": [0.0, 0.5], "downbeats": [0.0]})
    stage = AssembleStage()
    with pytest.raises(RuntimeError):
        stage.execute(ctx, {})


def _analysis(tmp_path, duration=4.0):
    return {
        "bpm": 120.0,
        "beats": [index * 0.5 for index in range(int(duration / 0.5) + 1)],
        "downbeats": [0.0, 2.0],
        "time_signature": "4/4",
        "duration": duration,
    }


def _project(tmp_path, name="dyn", **kwargs):
    ctx = ProjectContext(
        project_id=name,
        root=tmp_path / name,
        source=tmp_path / "song.mp3",
        log=lambda *_: None,
        **kwargs,
    )
    ctx.write_json(ctx.analysis_path, _analysis(tmp_path))
    return ctx


def _track_map(metrics):
    return {track["stem"]: track for track in metrics["per_track"]}


def test_assemble_solo_mode_metadata_and_per_track_midi(tmp_path):
    ctx = _project(tmp_path, "solo", mode="solo", instrument_id="erhu")
    _write_midi(
        ctx.midi_model_dir / "erhu.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 60 + index) for index in range(4)],
        program=110,
    )
    # Stale full-mode model output must be ignored in solo mode.
    _write_midi(ctx.midi_model_dir / "piano.mid", [(0.1, 0.4, 60)], program=0)

    outputs, metrics = AssembleStage().execute(ctx, {})

    payload = ctx.read_json(ctx.midi_final_dir / "tracks.json", {})
    assert payload["bpm"] == pytest.approx(120.0)
    assert [track["stem"] for track in payload["tracks"]] == ["erhu"]

    track = payload["tracks"][0]
    assert track["instrument_id"] == "erhu"
    assert track["display_name"] == "Erhu"
    assert track["program"] == 110
    assert track["is_drum"] is False
    assert track["source"] == "solo"
    assert track["notes"] == 4
    assert track["midi"] == "midi/final/erhu.mid"
    assert track["clef"] == "treble"
    assert track["transpose"] == 0
    assert track["confidence"] == pytest.approx(1.0)

    assert (ctx.root / track["midi"]).exists()
    written = pretty_midi.PrettyMIDI(str(ctx.root / track["midi"]))
    assert written.instruments[0].name == "erhu"
    assert written.instruments[0].program == 110
    assert "piano" not in outputs

    full = pretty_midi.PrettyMIDI(str(outputs["full"]))
    assert [instrument.name for instrument in full.instruments] == ["erhu"]


def test_assemble_adds_catalog_extra_track_with_program_and_metadata(tmp_path):
    ctx = _project(tmp_path, "extra")
    _write_midi(
        ctx.midi_model_dir / "piano.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 60 + index) for index in range(4)],
        program=0,
    )
    _write_midi(
        ctx.midi_model_dir / "violin.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 67 + index) for index in range(4)],
        program=40,
    )

    outputs, metrics = AssembleStage().execute(ctx, {})

    tracks = _track_map(metrics)
    assert tracks["piano"]["source"] == "core"
    assert tracks["piano"]["program"] == 0
    assert tracks["violin"]["source"] == "extra"
    assert tracks["violin"]["instrument_id"] == "violin"
    assert tracks["violin"]["display_name"] == "Violin"
    assert tracks["violin"]["program"] == 40
    assert tracks["violin"]["is_drum"] is False
    assert tracks["violin"]["midi"] == "midi/final/violin.mid"
    for track in tracks.values():
        assert (ctx.root / track["midi"]).exists()

    full = pretty_midi.PrettyMIDI(str(outputs["full"]))
    by_name = {instrument.name: instrument for instrument in full.instruments}
    assert by_name["violin"].program == 40
    assert metrics["tracks"] == 2


def test_assemble_marks_manual_stems_from_project_json(tmp_path):
    ctx = _project(tmp_path, "manual")
    ctx.write_json(ctx.root / "project.json", {"mode": "full", "manual_stems": ["erhu"]})
    _write_midi(
        ctx.midi_model_dir / "erhu.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 62 + index) for index in range(4)],
        program=110,
    )

    _, metrics = AssembleStage().execute(ctx, {})

    tracks = _track_map(metrics)
    assert tracks["erhu"]["source"] == "manual"
    assert tracks["erhu"]["instrument_id"] == "erhu"
    assert tracks["erhu"]["program"] == 110


def test_assemble_skips_effect_tracks(tmp_path):
    ctx = _project(tmp_path, "fx")
    _write_midi(
        ctx.midi_model_dir / "piano.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 60 + index) for index in range(4)],
        program=0,
    )
    _write_midi(
        ctx.midi_model_dir / "fx.mid",
        [(0.1 + index * 0.25, 0.3 + index * 0.25, 80 + index) for index in range(6)],
        program=0,
    )

    outputs, metrics = AssembleStage().execute(ctx, {})

    assert "fx" not in {track["stem"] for track in metrics["per_track"]}
    assert not (ctx.midi_final_dir / "fx.mid").exists()
    full = pretty_midi.PrettyMIDI(str(outputs["full"]))
    assert [instrument.name for instrument in full.instruments] == ["piano"]


def test_assemble_maps_muscriptor_synth_tracks_through_registry(tmp_path):
    ctx = _project(tmp_path, "synth")
    mix = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    specs = [
        ("muscriptor_synth lead", 80, [72, 74, 76, 79]),
        ("muscriptor_synth pad", 88, [48, 52, 55, 59]),
        # Core bass family: the dedicated bass stem owns it, so it is not added.
        ("muscriptor_synth bass", 38, [40, 43, 45, 47]),
        # Effect tracks must never become pitched tracks.
        ("muscriptor_fx", 99, [90, 92, 94, 96]),
    ]
    for name, program, pitches in specs:
        instrument = pretty_midi.Instrument(program=program, name=name)
        for index, pitch in enumerate(pitches):
            instrument.notes.append(
                pretty_midi.Note(100, pitch, 0.1 + index * 0.5, 0.4 + index * 0.5)
            )
        mix.instruments.append(instrument)
    ctx.midi_model_dir.mkdir(parents=True, exist_ok=True)
    mix.write(str(ctx.midi_model_dir / "muscriptor_mix.mid"))

    outputs, metrics = AssembleStage().execute(ctx, {})

    tracks = _track_map(metrics)
    assert tracks["muscriptor_synth lead"]["instrument_id"] == "synth_lead"
    assert tracks["muscriptor_synth lead"]["program"] == 80
    assert tracks["muscriptor_synth pad"]["instrument_id"] == "synth_pad"
    assert tracks["muscriptor_synth pad"]["program"] == 88
    assert tracks["muscriptor_synth lead"]["source"] == "extra"
    assert "muscriptor_synth bass" not in tracks
    assert "muscriptor_fx" not in tracks
    assert metrics["tracks"] == 2
    for track in tracks.values():
        assert (ctx.root / track["midi"]).exists()

    full = pretty_midi.PrettyMIDI(str(outputs["full"]))
    programs = {instrument.name: instrument.program for instrument in full.instruments}
    assert programs["muscriptor_synth lead"] == 80
    assert programs["muscriptor_synth pad"] == 88


def test_assemble_resolves_synthetic_program_labels(tmp_path):
    ctx = _project(tmp_path, "program")
    mix = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=45, name="muscriptor_program 45")
    for index in range(8):
        instrument.notes.append(
            pretty_midi.Note(90, 60 + index, 0.1 + index * 0.4, 0.3 + index * 0.4)
        )
    mix.instruments.append(instrument)
    ctx.midi_model_dir.mkdir(parents=True, exist_ok=True)
    mix.write(str(ctx.midi_model_dir / "muscriptor_mix.mid"))

    _, metrics = AssembleStage().execute(ctx, {})

    tracks = _track_map(metrics)
    track = tracks["muscriptor_program 45"]
    assert track["instrument_id"] == "program_45"
    assert track["program"] == 45
    assert track["source"] == "extra"
    assert (ctx.root / track["midi"]).exists()


def test_assemble_percussion_extra_track_is_a_drum_track(tmp_path):
    ctx = _project(tmp_path, "perc")
    _write_midi(
        ctx.midi_model_dir / "tabla.mid",
        [(0.1, 0.2, 36), (0.6, 0.7, 38), (1.1, 1.2, 42), (1.6, 1.7, 45)],
        program=0,
    )

    outputs, metrics = AssembleStage().execute(ctx, {})

    track = _track_map(metrics)["tabla"]
    assert track["instrument_id"] == "tabla"
    assert track["is_drum"] is True
    assert track["program"] == 0
    assert (ctx.root / track["midi"]).exists()

    written = pretty_midi.PrettyMIDI(str(ctx.root / track["midi"]))
    assert written.instruments[0].is_drum is True

    full = pretty_midi.PrettyMIDI(str(outputs["full"]))
    assert full.instruments[0].is_drum is True
    assert full.instruments[0].name == "tabla"


def test_assemble_tracks_json_keeps_bpm_for_every_track(tmp_path):
    ctx = _project(tmp_path, "bpm")
    _write_midi(
        ctx.midi_model_dir / "piano.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 60 + index) for index in range(4)],
        program=0,
    )
    _write_midi(
        ctx.midi_model_dir / "erhu.mid",
        [(0.1 + index * 0.5, 0.4 + index * 0.5, 70 + index) for index in range(4)],
        program=110,
    )

    _, metrics = AssembleStage().execute(ctx, {})

    payload = ctx.read_json(ctx.midi_final_dir / "tracks.json", {})
    assert payload["bpm"] == pytest.approx(120.0)
    required = {
        "stem",
        "instrument_id",
        "display_name",
        "program",
        "is_drum",
        "notes",
        "source",
        "midi",
    }
    for track in payload["tracks"]:
        assert required <= set(track)
        assert track["source"] in {"core", "solo", "extra", "manual"}
        assert (ctx.root / track["midi"]).exists()
    assert len(payload["tracks"]) == 2
