from __future__ import annotations

from app.models.adapters.common import monophonic_filter
from app.models.adapters.separation import classify_stem
from app.types import NoteEvent


def test_monophonic_filter_resolves_overlap():
    notes = [
        NoteEvent(0.0, 1.0, 60, velocity=100),
        NoteEvent(0.5, 1.5, 64, velocity=50),
    ]
    result = monophonic_filter(notes)
    assert len(result) == 2
    for first, second in zip(result, result[1:]):
        assert first.end <= second.start + 0.02


def test_monophonic_filter_keeps_stronger_note():
    notes = [
        NoteEvent(0.0, 0.6, 60, velocity=80),
        NoteEvent(0.1, 0.5, 64, velocity=110),
    ]
    result = monophonic_filter(notes)
    pitches = [note.pitch for note in result]
    assert 64 in pitches


def test_classify_stem_filenames():
    assert classify_stem("song_(Vocals)_htdemucs.wav") == "vocals"
    assert classify_stem("song_(Drums)_htdemucs.wav") == "drums"
    assert classify_stem("song_(Bass)_htdemucs.wav") == "bass"
    assert classify_stem("song_(Guitar)_htdemucs.wav") == "guitar"
    assert classify_stem("song_(Piano)_htdemucs.wav") == "piano"
    assert classify_stem("song_(Instrumental)_mdx.wav") == "other"
    assert classify_stem("song_(Other)_htdemucs.wav") == "other"
    assert classify_stem("nothing-here.wav") is None
