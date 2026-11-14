from __future__ import annotations

import pretty_midi
import pytest

from app.services.notation import midi_to_musicxml, split_musicxml_parts


def _simple_midi(path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=0)
    for index, pitch in enumerate([60, 64, 67]):
        instrument.notes.append(
            pretty_midi.Note(100, pitch, start=index * 0.5, end=(index + 1) * 0.5)
        )
    midi.instruments.append(instrument)
    midi.write(str(path))


def test_piano_part_becomes_grand_staff(tmp_path):
    source = tmp_path / "piano.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=0, name="piano")
    for index, pitch in enumerate([48, 55, 60, 67, 72, 79]):
        instrument.notes.append(
            pretty_midi.Note(96, pitch, start=index * 0.5, end=(index + 1) * 0.5)
        )
    midi.instruments.append(instrument)
    midi.write(str(source))

    target = tmp_path / "piano.musicxml"
    midi_to_musicxml(source, target, title="Piano")

    text = target.read_text(encoding="utf-8")
    assert text.count("<staves>2</staves>") == 1
    assert text.count("<part-name>Piano</part-name>") == 1
    assert "<sign>G</sign>" in text and "<sign>F</sign>" in text
    assert "Music21" not in text


def test_drum_part_uses_percussion_notation(tmp_path):
    source = tmp_path / "drums.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=0, is_drum=True, name="drums")
    for index, pitch in enumerate([36, 38, 42, 49]):
        instrument.notes.append(
            pretty_midi.Note(110, pitch, start=index * 0.5, end=index * 0.5 + 0.2)
        )
    midi.instruments.append(instrument)
    midi.write(str(source))

    target = tmp_path / "drums.musicxml"
    midi_to_musicxml(source, target, title="Drums")

    text = target.read_text(encoding="utf-8")
    assert text.count("<unpitched>") == 4
    assert text.count("<notehead") >= 2  # hi-hat and crash use x noteheads
    assert "<sign>percussion</sign>" in text
    assert "<display-step>F</display-step>" in text
    assert "<display-step>G</display-step>" in text

    from music21 import converter

    score = converter.parse(str(target))
    notes = list(score.recurse().notes)
    assert notes


def test_drum_ghost_note_uses_parentheses(tmp_path):
    source = tmp_path / "ghost.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=0, is_drum=True, name="drums")
    instrument.notes.append(pretty_midi.Note(30, 38, start=0.0, end=0.2))
    instrument.notes.append(pretty_midi.Note(110, 36, start=0.5, end=0.7))
    midi.instruments.append(instrument)
    midi.write(str(source))

    target = tmp_path / "ghost.musicxml"
    midi_to_musicxml(source, target, title="Drums")
    text = target.read_text(encoding="utf-8")
    assert 'parentheses="yes"' in text
    assert text.count("<unpitched>") == 2



def test_lyrics_are_attached_to_vocal_notes(tmp_path):
    source = tmp_path / "vocal.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=53, name="vocals")
    for index, pitch in enumerate([60, 62, 64, 65]):
        instrument.notes.append(
            pretty_midi.Note(90, pitch, start=index * 0.5, end=index * 0.5 + 0.4)
        )
    midi.instruments.append(instrument)
    midi.write(str(source))

    lyrics = {
        "language": "en",
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "hello world again now",
                "words": [
                    {"start": 0.0, "end": 0.45, "word": "hello"},
                    {"start": 0.5, "end": 0.95, "word": "world"},
                    {"start": 1.0, "end": 1.45, "word": "again"},
                    {"start": 1.5, "end": 1.95, "word": "now"},
                ],
            }
        ],
    }
    target = tmp_path / "vocal.musicxml"
    midi_to_musicxml(source, target, title="Vocal", lyrics=lyrics)

    text = target.read_text(encoding="utf-8")
    assert text.count("<lyric") >= 4
    for word in ("hello", "world", "again", "now"):
        assert f"<text>{word}</text>" in text


def test_midi_to_musicxml_roundtrip(tmp_path):
    source = tmp_path / "melody.mid"
    _simple_midi(source)

    target = tmp_path / "melody.musicxml"
    midi_to_musicxml(source, target, title="Test Melody")

    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "score-partwise" in text
    assert "Test Melody" in text

    from music21 import converter

    score = converter.parse(str(target))
    notes = list(score.recurse().notes)
    pitch_count = sum(len(note.pitches) for note in notes)
    assert pitch_count >= 3


def test_render_svg_supports_unicode_path(tmp_path):
    pytest.importorskip("verovio")
    from app.services.notation import render_svg

    source = tmp_path / "melody.mid"
    _simple_midi(source)
    score_dir = tmp_path / "中文项目" / "score"
    score_dir.mkdir(parents=True, exist_ok=True)
    musicxml = midi_to_musicxml(source, score_dir / "full.musicxml")
    timemap = score_dir / "full.timemap.json"

    pages = render_svg(musicxml, score_dir / "full.svg", timemap)

    assert pages and pages[0].exists()
    assert pages[0].stat().st_size > 100
    assert timemap.stat().st_size > 2


def test_split_musicxml_parts_preserves_parts(tmp_path):
    source = tmp_path / "duet.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    for program, name, pitch in ((40, "violin", 76), (0, "piano", 60)):
        instrument = pretty_midi.Instrument(program=program, name=name)
        instrument.notes.append(pretty_midi.Note(90, pitch, 0.0, 1.0))
        midi.instruments.append(instrument)
    midi.write(str(source))

    musicxml = midi_to_musicxml(source, tmp_path / "duet.musicxml")
    paths = split_musicxml_parts(musicxml, tmp_path / "parts")

    assert len(paths) == 2
    from music21 import converter

    for path in paths:
        single = converter.parse(str(path))
        # Grand-staff parts (piano) import as two PartStaff objects.
        assert len(single.parts) >= 1
        assert single.parts[0].partName
