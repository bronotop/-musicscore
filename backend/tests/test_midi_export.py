from __future__ import annotations

import json

import mido
import pretty_midi

from app import main


def _write_track(path, name: str, program: int, pitch: int) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=program, name=name)
    instrument.notes.append(pretty_midi.Note(90, pitch, 0.0, 0.5))
    midi.instruments.append(instrument)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def test_track_exports_match_full_midi_after_edit(tmp_path):
    root = tmp_path / "project"
    final = root / "midi" / "final"
    (root / "stems").mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"project_id": "project", "mode": "full", "preset": "fast"}),
        encoding="utf-8",
    )
    _write_track(final / "piano.mid", "Piano", 0, 60)
    _write_track(final / "violin.mid", "Violin", 40, 76)

    full = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    for name, program, pitch in (("Piano", 0, 60), ("Violin", 40, 76)):
        instrument = pretty_midi.Instrument(program=program, name=name)
        instrument.notes.append(pretty_midi.Note(90, pitch, 0.0, 0.5))
        full.instruments.append(instrument)
    full.write(str(final / "full.mid"))

    previous = [
        {
            "stem": "piano",
            "instrument_id": "piano",
            "display_name": "Grand Piano",
            "program": 0,
            "is_drum": False,
            "notes": 1,
            "source": "core",
            "midi": "midi/final/piano.mid",
        },
        {
            "stem": "violin",
            "instrument_id": "violin",
            "display_name": "Violin",
            "program": 40,
            "is_drum": False,
            "notes": 1,
            "source": "extra",
            "midi": "midi/final/violin.mid",
        },
    ]
    (final / "tracks.json").write_text(
        json.dumps({"tracks": previous, "bpm": 120.0}), encoding="utf-8"
    )

    edited = pretty_midi.PrettyMIDI(str(final / "full.mid"))
    edited.instruments[0].program = 1
    edited.instruments[0].name = "Grand Piano"
    edited.write(str(final / "full.mid"))

    tracks = main.rebuild_tracks(root, final / "full.mid")
    main._sync_track_midi_files(root, tracks)

    piano = pretty_midi.PrettyMIDI(str(final / "piano.mid"))
    assert piano.instruments[0].program == 1
    assert piano.instruments[0].name == "Grand Piano"
    assert len(piano.instruments[0].notes) == 1

    full_mido = mido.MidiFile(str(final / "full.mid"))
    assert full_mido.type == 1
    assert len(full_mido.tracks) >= 3
    for path in (final / "piano.mid", final / "violin.mid"):
        parsed = mido.MidiFile(str(path))
        note_ons = [
            message
            for track in parsed.tracks
            for message in track
            if message.type == "note_on" and message.velocity > 0
        ]
        assert note_ons, path
