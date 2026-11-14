from __future__ import annotations

import pretty_midi

from app.services.notation import midi_to_musicxml


def _vocal_midi(path, notes):
    """Write a synthetic vocal MIDI from (pitch, start, end) tuples."""
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    instrument = pretty_midi.Instrument(program=53, name="vocals")
    for pitch, start, end in notes:
        instrument.notes.append(
            pretty_midi.Note(90, pitch, start=start, end=end)
        )
    midi.instruments.append(instrument)
    midi.write(str(path))


def _payload(*words, language="en"):
    return {
        "language": language,
        "segments": [
            {
                "start": words[0][0],
                "end": words[-1][1],
                "text": " ".join(word[2] for word in words),
                "words": [
                    {"start": start, "end": end, "word": word}
                    for start, end, word in words
                ],
            }
        ],
    }


def _note_lyrics(xml_path):
    """Return [(offset, lyric)] for the vocal part in output order."""
    from music21 import converter

    score = converter.parse(str(xml_path))
    part = score.parts[0]
    notes = []
    for entry in part.flatten().secondsMap:
        element = entry.get("element")
        if element is not None and getattr(element, "isNote", False):
            notes.append((float(entry.get("offsetSeconds", 0.0)), element.lyric))
    notes.sort(key=lambda item: item[0])
    return [lyric for _, lyric in notes]


def test_english_word_spans_three_notes_is_not_repeated(tmp_path):
    source = tmp_path / "melisma.mid"
    _vocal_midi(
        source,
        [(60, 0.0, 0.45), (62, 0.5, 0.95), (64, 1.0, 1.45)],
    )
    lyrics = _payload((0.0, 1.45, " sing "))

    target = tmp_path / "melisma.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    assert target.read_text(encoding="utf-8").count("<text>sing</text>") == 1
    # The melisma tail stays empty so the word is not repeated.
    assert _note_lyrics(target) == ["sing", None, None]


def test_adjacent_words_are_not_merged_into_one_note(tmp_path):
    source = tmp_path / "adjacent.mid"
    _vocal_midi(source, [(60, 0.0, 0.45), (62, 0.5, 0.95)])
    lyrics = _payload((0.0, 0.45, "one"), (0.5, 0.95, "two"))

    target = tmp_path / "adjacent.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    text = target.read_text(encoding="utf-8")
    assert text.count("<text>one</text>") == 1
    assert text.count("<text>two</text>") == 1
    assert _note_lyrics(target) == ["one", "two"]


def test_english_word_is_split_into_syllables_when_it_spans_notes(tmp_path):
    source = tmp_path / "syllables.mid"
    _vocal_midi(source, [(60, 0.0, 0.45), (62, 0.5, 0.95)])
    lyrics = _payload((0.0, 0.9, "hello"))

    target = tmp_path / "syllables.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    text = target.read_text(encoding="utf-8")
    assert "<text>hel</text>" in text
    assert "<text>lo</text>" in text
    assert "<syllabic>begin</syllabic>" in text
    assert "<syllabic>end</syllabic>" in text
    assert _note_lyrics(target) == ["hel", "lo"]


def test_chinese_characters_are_distributed_one_per_note(tmp_path):
    source = tmp_path / "chinese.mid"
    _vocal_midi(
        source,
        [(60, 0.0, 0.45), (62, 0.5, 0.95), (64, 1.0, 1.45), (65, 1.5, 1.95)],
    )
    lyrics = _payload((0.0, 2.0, "你好世界"), language="zh")

    target = tmp_path / "chinese.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    assert _note_lyrics(target) == ["你", "好", "世", "界"]


def test_chinese_surplus_characters_merge_into_last_note(tmp_path):
    source = tmp_path / "chinese-overflow.mid"
    _vocal_midi(source, [(60, 0.0, 0.45), (62, 0.5, 0.95)])
    lyrics = _payload((0.0, 1.0, "你好世界"), language="zh")

    target = tmp_path / "chinese-overflow.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    assert _note_lyrics(target) == ["你", "好世界"]


def test_punctuation_and_empty_words_do_not_consume_notes(tmp_path):
    source = tmp_path / "punctuation.mid"
    _vocal_midi(source, [(60, 0.0, 0.45), (62, 0.5, 0.95)])
    lyrics = _payload(
        (0.0, 0.2, "..."), (0.25, 0.4, "!"), (0.5, 0.95, " Hello, ")
    )

    target = tmp_path / "punctuation.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    assert _note_lyrics(target) == [None, "Hello"]


def test_word_without_overlap_uses_nearest_free_note(tmp_path):
    source = tmp_path / "nearest.mid"
    _vocal_midi(source, [(60, 0.0, 0.45)])
    lyrics = _payload((0.6, 0.9, "late"))

    target = tmp_path / "nearest.musicxml"
    midi_to_musicxml(source, target, lyrics=lyrics)

    assert _note_lyrics(target) == ["late"]
