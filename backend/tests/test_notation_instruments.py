from __future__ import annotations

import json
import re

import pretty_midi
from music21 import converter

from app.pipeline.stages.notate import _load_track_profiles
from app.services.notation import midi_to_musicxml, split_musicxml_parts


def _write_midi(path, tracks):
    """tracks: iterable of ``(name, program, pitches, is_drum)``."""
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    for name, program, pitches, is_drum in tracks:
        instrument = pretty_midi.Instrument(
            program=program, name=name, is_drum=is_drum
        )
        for index, pitch in enumerate(pitches):
            instrument.notes.append(
                pretty_midi.Note(
                    velocity=90,
                    pitch=pitch,
                    start=index * 0.5,
                    end=index * 0.5 + 0.4,
                )
            )
        midi.instruments.append(instrument)
    midi.write(str(path))


def test_notate_stage_reads_tracks_json(tmp_path):
    class FakeContext:
        midi_final_dir = tmp_path

        @staticmethod
        def read_json(path, default=None):
            return json.loads(path.read_text(encoding="utf-8"))

    payload = {
        "bpm": 120.0,
        "tracks": [
            {
                "stem": "erhu",
                "instrument_id": "erhu",
                "display_name": "Erhu",
                "program": 110,
                "is_drum": False,
                "clef": "treble",
                "transpose": 0,
            }
        ],
    }
    (tmp_path / "tracks.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    profiles = _load_track_profiles(FakeContext())
    assert profiles["erhu"]["instrument_id"] == "erhu"
    assert profiles["erhu"]["clef"] == "treble"


def _clef_text(target):
    text = target.read_text(encoding="utf-8")
    clefs = re.findall(r"<clef>.*?</clef>", text, re.S)
    return clefs[0] if clefs else ""


def _written_midi(path):
    score = converter.parse(str(path))
    notes = list(score.parts[0].recurse().notes)
    assert notes
    return notes[0].pitch.midi


def _written_midis(path):
    score = converter.parse(str(path))
    return [note.pitch.midi for note in score.parts[0].recurse().notes]


def test_viola_gets_alto_clef(tmp_path):
    source = tmp_path / "viola.mid"
    _write_midi(source, [("viola", 41, [60, 64, 67], False)])
    target = tmp_path / "viola.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={"viola": {"instrument_id": "viola", "program": 41}},
    )

    clef = _clef_text(target)
    assert "<sign>C</sign>" in clef
    assert "<line>3</line>" in clef
    assert "<part-name>Viola</part-name>" in target.read_text(encoding="utf-8")


def test_cello_and_trombone_get_bass_clef(tmp_path):
    for label, program, name in (
        ("cello", 42, "Cello"),
        ("trombone", 57, "Trombone"),
    ):
        source = tmp_path / f"{label}.mid"
        _write_midi(source, [(label, program, [48, 52, 55], False)])
        target = tmp_path / f"{label}.musicxml"
        midi_to_musicxml(source, target)

        clef = _clef_text(target)
        assert "<sign>F</sign>" in clef
        assert "<line>4</line>" in clef
        assert f"<part-name>{name}</part-name>" in target.read_text(encoding="utf-8")


def test_guitar_gets_treble_8vb_clef(tmp_path):
    source = tmp_path / "guitar.mid"
    _write_midi(source, [("guitar", 25, [55, 59, 62], False)])
    target = tmp_path / "guitar.musicxml"
    midi_to_musicxml(source, target)

    clef = _clef_text(target)
    assert "<sign>G</sign>" in clef
    assert "<clef-octave-change>-1</clef-octave-change>" in clef


def test_muscriptor_label_resolves_to_catalog_name(tmp_path):
    source = tmp_path / "sax.mid"
    _write_midi(source, [("muscriptor_tenor sax", 66, [60, 62, 64], False)])
    target = tmp_path / "sax.musicxml"
    midi_to_musicxml(source, target)

    text = target.read_text(encoding="utf-8")
    assert "<part-name>Tenor Sax</part-name>" in text
    assert "muscriptor" not in text


def test_trumpet_written_pitch_is_a_major_second_higher(tmp_path):
    source = tmp_path / "trumpet.mid"
    _write_midi(source, [("trumpet", 56, [60, 62, 64, 65], False)])
    target = tmp_path / "trumpet.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={
            "trumpet": {
                "stem": "trumpet",
                "instrument_id": "trumpet",
                "program": 56,
                "clef": "treble",
                "transpose": 2,
            }
        },
    )

    text = target.read_text(encoding="utf-8")
    # Exactly one transpose element: the part must not be transposed twice.
    assert text.count("<transpose>") == 1
    assert "<chromatic>-2</chromatic>" in text
    assert "<diatonic>-1</diatonic>" in text
    assert "<part-name>Trumpet</part-name>" in text

    # Written pitch is a whole tone above the concert-pitch MIDI.
    assert _written_midis(target) == [62, 64, 66, 67]
    score = converter.parse(str(target))
    sounding = [
        note.pitch.midi
        for note in score.parts[0].toSoundingPitch().recurse().notes
    ]
    assert sounding == [60, 62, 64, 65]


def test_unknown_program_is_labelled_other(tmp_path):
    source = tmp_path / "mystery.mid"
    _write_midi(source, [("mystery", 99, [60, 62, 64], False)])
    target = tmp_path / "mystery.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={
            "mystery": {
                "stem": "mystery",
                "instrument_id": "program_99",
                "program": 99,
                "clef": "treble",
                "transpose": 0,
            }
        },
    )

    text = target.read_text(encoding="utf-8")
    assert "<part-name>Other (program 99)</part-name>" in text
    assert "program_99" not in text


def test_unknown_program_without_metadata_uses_other(tmp_path):
    source = tmp_path / "program_99.mid"
    _write_midi(source, [("program_99", 99, [60, 62, 64], False)])
    target = tmp_path / "program_99.musicxml"
    midi_to_musicxml(source, target)

    text = target.read_text(encoding="utf-8")
    assert "<part-name>Other (program 99)</part-name>" in text
    assert "program_99" not in text


def test_grand_profile_still_emits_two_staves(tmp_path):
    source = tmp_path / "piano.mid"
    _write_midi(source, [("piano", 0, [48, 55, 60, 67, 72, 79], False)])
    target = tmp_path / "piano.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={"piano": {"instrument_id": "piano", "clef": "grand"}},
    )

    text = target.read_text(encoding="utf-8")
    assert text.count("<staves>2</staves>") == 1
    assert "<part-name>Piano</part-name>" in text


def test_percussion_profile_converts_plain_midi_to_unpitched(tmp_path):
    source = tmp_path / "tabla.mid"
    _write_midi(source, [("tabla", 0, [36, 38, 42], False)])
    target = tmp_path / "tabla.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={
            "tabla": {
                "instrument_id": "tabla",
                "program": 0,
                "clef": "percussion",
                "notation": "percussion",
            }
        },
    )

    text = target.read_text(encoding="utf-8")
    assert "<part-name>Tabla</part-name>" in text
    assert "<sign>percussion</sign>" in text
    assert text.count("<unpitched>") == 3


def test_notation_none_part_is_skipped(tmp_path):
    source = tmp_path / "fx.mid"
    _write_midi(
        source,
        [
            ("fx", 0, [60, 62, 64], False),
            ("violin", 40, [60, 64, 67], False),
        ],
    )
    target = tmp_path / "fx.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={
            "fx": {"instrument_id": "fx", "notation": "none"},
            "violin": {"instrument_id": "violin"},
        },
    )

    text = target.read_text(encoding="utf-8")
    assert "<part-name>FX</part-name>" not in text
    assert "<part-name>Violin</part-name>" in text
    assert text.count("<score-part ") == 1


def test_split_parts_keeps_grand_staff_and_transposition(tmp_path):
    source = tmp_path / "mixed.mid"
    _write_midi(
        source,
        [
            ("piano", 0, [48, 55, 60, 67, 72], False),
            ("trumpet", 56, [60, 62, 64], False),
        ],
    )
    target = tmp_path / "mixed.musicxml"
    midi_to_musicxml(
        source,
        target,
        track_profiles={
            "piano": {"instrument_id": "piano", "clef": "grand"},
            "trumpet": {"instrument_id": "trumpet", "transpose": 2},
        },
    )

    parts = split_musicxml_parts(target, tmp_path / "parts")
    assert len(parts) == 2
    by_name = {path.name: path for path in parts}

    piano_file = next(path for name, path in by_name.items() if "Piano" in name)
    trumpet_file = next(path for name, path in by_name.items() if "Trumpet" in name)

    piano_text = piano_file.read_text(encoding="utf-8")
    assert "<staves>2</staves>" in piano_text

    trumpet_text = trumpet_file.read_text(encoding="utf-8")
    assert trumpet_text.count("<transpose>") == 1
    assert "<chromatic>-2</chromatic>" in trumpet_text
    assert _written_midi(trumpet_file) == 62
