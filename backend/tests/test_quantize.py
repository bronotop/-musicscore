from __future__ import annotations

import numpy as np
import pytest

from app.services.quantize import BeatGridQuantizer, infer_time_signature, regular_beats
from app.types import NoteEvent


def test_regular_beats_120_bpm():
    beats = regular_beats(2.0, 120.0)
    assert beats[0] == pytest.approx(0.0)
    assert beats[1] == pytest.approx(0.5)
    assert len(beats) >= 4


def test_quantizer_snaps_to_sixteenth_grid():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    quantizer = BeatGridQuantizer(beats, subdivision=4)
    notes = [NoteEvent(start=0.16, end=0.36, pitch=60)]
    result = quantizer.quantize_notes(notes)
    assert result[0].start == pytest.approx(0.125)
    assert result[0].end == pytest.approx(0.375)
    assert result[0].pitch == 60


def test_quantizer_extends_zero_length_notes():
    quantizer = BeatGridQuantizer([0.0, 0.5, 1.0], subdivision=4)
    result = quantizer.quantize_notes([NoteEvent(0.01, 0.02, 64)])
    assert result[0].end > result[0].start


def test_quantizer_extrapolates_after_last_beat():
    quantizer = BeatGridQuantizer([0.0, 0.5, 1.0], subdivision=4)
    result = quantizer.quantize_notes([NoteEvent(1.2, 1.35, 60)])
    assert result[0].start == pytest.approx(1.25)
    assert result[0].end == pytest.approx(1.25 + 0.125)


def test_infer_time_signature_four_four():
    beats = [i * 0.5 for i in range(9)]
    downbeats = [0.0, 2.0, 4.0]
    signature, confidence = infer_time_signature(beats, downbeats)
    assert signature == "4/4"
    assert confidence == pytest.approx(1.0)


def test_infer_time_signature_three_four():
    beats = [i * 0.5 for i in range(7)]
    downbeats = [0.0, 1.5, 3.0]
    signature, _ = infer_time_signature(beats, downbeats)
    assert signature == "3/4"
