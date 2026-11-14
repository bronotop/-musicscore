from __future__ import annotations

import os

import pytest

from app.services.fusion import (
    DEFAULT_PROFILES,
    EvidenceIndex,
    FusionProfile,
    enforce_quantized_limits,
    fuse_notes,
    profile_for,
)
from app.types import NoteEvent


def _clean_profile(**overrides) -> FusionProfile:
    base = dict(
        min_confidence=0.0,
        min_duration=0.0,
        short_note_confidence=0.0,
        max_polyphony=0,
        density_limit=0.0,
        octave_merge=False,
        support_bonus=0.0,
    )
    base.update(overrides)
    return FusionProfile(**base)


def test_filters_low_confidence_and_short_fragments():
    profile = _clean_profile(
        min_confidence=0.30,
        min_duration=0.06,
        short_note_confidence=0.40,
    )
    notes = [
        NoteEvent(0.0, 0.04, 60, 60, 0.20),  # short and uncertain
        NoteEvent(0.5, 0.54, 62, 80, 0.35),  # short, below short_note_confidence
        NoteEvent(1.0, 1.04, 64, 80, 0.90),  # short but confident: keep
        NoteEvent(1.5, 2.0, 65, 80, 0.90),   # normal note: keep
        NoteEvent(2.5, 3.0, 67, 80, 0.20),   # long but uncertain
    ]

    kept, stats = fuse_notes("guitar", notes, profile=profile)

    assert [note.pitch for note in kept] == [64, 65]
    assert stats["before"] == 5
    assert stats["after"] == 2
    assert stats["removed"]["low_confidence"] == 2
    assert stats["removed"]["short_fragment"] == 1


def test_same_pitch_overlap_keeps_higher_score():
    profile = _clean_profile()
    notes = [
        NoteEvent(1.0, 1.5, 60, 60, 0.40),
        NoteEvent(1.1, 1.6, 60, 110, 0.80),
    ]

    kept, stats = fuse_notes("guitar", notes, profile=profile)

    assert len(kept) == 1
    assert kept[0].confidence == pytest.approx(0.80)
    assert stats["removed"]["same_pitch_duplicate"] == 1


def test_octave_duplicate_keeps_one_note():
    profile = _clean_profile(
        octave_merge=True,
        octave_policy="confidence",
        octave_window=0.10,
        octave_overlap=0.85,
    )
    notes = [
        NoteEvent(1.0, 2.0, 60, 100, 0.40),
        NoteEvent(1.02, 1.90, 72, 100, 0.85),
    ]

    kept, stats = fuse_notes("guitar", notes, profile=profile)

    assert [note.pitch for note in kept] == [72]
    assert stats["removed"]["octave_duplicate"] == 1

    low_profile = FusionProfile(**{**profile.__dict__, "octave_policy": "low"})
    kept_low, _ = fuse_notes("guitar", notes, profile=low_profile)
    assert [note.pitch for note in kept_low] == [60]


def test_octave_merge_disabled_for_piano_by_default():
    assert DEFAULT_PROFILES["piano"].octave_merge is False
    assert DEFAULT_PROFILES["guitar"].octave_merge is True


def test_polyphony_cap_keeps_strongest_notes():
    profile = _clean_profile(max_polyphony=4)
    pitches = [60, 62, 64, 65, 67, 69]
    notes = [
        NoteEvent(1.0, 2.0, pitch, 40 + index * 10, 0.90)
        for index, pitch in enumerate(pitches)
    ]

    kept, stats = fuse_notes("guitar", notes, profile=profile)

    assert len(kept) == 4
    assert {note.pitch for note in kept} == {64, 65, 67, 69}
    assert stats["removed"]["polyphony"] == 2


def test_density_cap_limits_a_dense_window():
    profile = _clean_profile(density_limit=4.0, density_window=1.0)
    notes = [
        NoteEvent(index * 0.05, index * 0.05 + 0.04, 60 + index % 3, 60 + index, 0.90)
        for index in range(12)
    ]

    kept, stats = fuse_notes("other", notes, profile=profile)

    assert len(kept) == 4
    assert stats["removed"]["density"] == 8


def test_cross_model_evidence_protects_a_weak_note():
    profile = _clean_profile(
        min_confidence=0.30,
        support_bonus=0.50,
        support_tolerance=0.10,
    )
    note = NoteEvent(1.0, 1.2, 60, 80, 0.20)
    evidence = EvidenceIndex([NoteEvent(1.02, 1.30, 60, 100, 1.0)])

    without, stats_without = fuse_notes("guitar", [note], profile=profile)
    assert without == []
    assert stats_without["removed"]["low_confidence"] == 1

    with_evidence, stats_with = fuse_notes(
        "guitar", [note], evidence=evidence, profile=profile
    )
    assert len(with_evidence) == 1
    assert with_evidence[0].confidence == pytest.approx(0.60)
    assert stats_with["supported"] == 1
    assert stats_with["removed"]["low_confidence"] == 0


def test_monophonic_cap_keeps_distinct_onsets():
    profile = _clean_profile(min_confidence=0.30, max_polyphony=1)
    notes = [
        NoteEvent(0.0, 0.40, 60, 90, 0.90),
        NoteEvent(0.45, 0.85, 62, 90, 0.90),
        NoteEvent(0.90, 1.30, 64, 90, 0.90),
    ]

    kept, stats = fuse_notes("vocals", notes, profile=profile)

    assert [note.pitch for note in kept] == [60, 62, 64]
    assert stats["after"] == 3
    assert stats["removed"]["polyphony"] == 0


def test_monophonic_cap_drops_overlapping_harmonic():
    profile = _clean_profile(min_confidence=0.30, max_polyphony=1)
    notes = [
        NoteEvent(0.0, 1.0, 36, 100, 0.90),  # sustained root
        NoteEvent(0.2, 0.6, 48, 80, 0.50),   # quieter octave harmonic
    ]

    kept, stats = fuse_notes("bass", notes, profile=profile)

    assert [note.pitch for note in kept] == [36]
    assert kept[0].end == pytest.approx(1.0)  # root duration is not truncated
    assert stats["removed"]["polyphony"] == 1


def test_profile_environment_overrides(monkeypatch):
    for key in list(os.environ):
        if key.startswith("M2S_FUSION_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("M2S_FUSION_MIN_CONFIDENCE", "0.55")
    monkeypatch.setenv("M2S_FUSION_MIN_DURATION_MS", "80")
    monkeypatch.setenv("M2S_FUSION_GUITAR_MAX_POLYPHONY", "2")
    monkeypatch.setenv("M2S_FUSION_MUSCRIPTOR_MIN_CONFIDENCE", "0.44")
    monkeypatch.setenv("M2S_FUSION_MUSCRIPTOR_MAX_POLYPHONY", "3")
    monkeypatch.setenv("M2S_FUSION_MUSCRIPTOR_BARITONE_SAX_MAX_POLYPHONY", "1")

    guitar = profile_for("guitar")
    other = profile_for("other")
    sax = profile_for("muscriptor_baritone sax")

    assert guitar.min_confidence == pytest.approx(0.55)
    assert guitar.max_polyphony == 2
    assert guitar.min_duration == pytest.approx(0.08)

    assert other.min_confidence == pytest.approx(0.55)
    assert other.max_polyphony == 6  # instrument default, no override

    assert sax.min_confidence == pytest.approx(0.44)
    assert sax.max_polyphony == 1  # exact stem name beats the family default


def test_enforce_quantized_limits_reapplies_polyphony_cap():
    profile = _clean_profile(max_polyphony=2)
    notes = [
        NoteEvent(0.0, 0.5, pitch, 100, 0.90) for pitch in (60, 62, 64)
    ]

    kept, stats = enforce_quantized_limits("guitar", notes, profile=profile)

    assert len(kept) == 2
    assert stats["removed"]["polyphony"] == 1
    assert stats["after"] == 2
