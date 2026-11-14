from __future__ import annotations

from app.services.piano_hands import DEFAULT_SPLIT, choose_split_pitch


def test_clear_two_register_piano_uses_adaptive_split():
    pitches = list(range(40, 56)) + list(range(64, 84))
    split = choose_split_pitch(pitches)
    assert 48 <= split <= 72
    assert split < 64
    assert split > 55


def test_uniform_register_keeps_middle_c():
    pitches = list(range(60, 84))
    assert choose_split_pitch(pitches) == DEFAULT_SPLIT


def test_too_few_notes_keeps_default():
    assert choose_split_pitch([48, 52, 67, 72]) == DEFAULT_SPLIT


def test_overlapping_registers_keep_default():
    pitches = list(range(55, 76)) + list(range(58, 80))
    assert choose_split_pitch(pitches) == DEFAULT_SPLIT
