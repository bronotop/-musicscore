from __future__ import annotations

import pytest
import numpy as np
import soundfile as sf

from app.services.audio import decode_to_wav, load_audio, probe, write_wav


def test_decode_resamples_and_downmixes(tmp_path):
    source = tmp_path / "source.wav"
    sr = 48000
    t = np.arange(sr, dtype=np.float32) / sr
    stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)], axis=1)
    sf.write(str(source), stereo, sr)

    target = tmp_path / "decoded.wav"
    decode_to_wav(source, target, sample_rate=44100, channels=1)

    info = probe(target)
    assert info.sample_rate == 44100
    assert info.channels == 1
    assert info.duration == pytest.approx(1.0, abs=0.02)


def test_load_audio_resamples(tmp_path):
    source = tmp_path / "source.wav"
    sr = 48000
    t = np.arange(sr, dtype=np.float32) / sr
    sf.write(str(source), np.sin(2 * np.pi * 440 * t), sr)

    audio, rate = load_audio(source, sample_rate=44100, mono=True)
    assert rate == 44100
    assert audio.shape[0] == 1
    assert audio.shape[1] == pytest.approx(44100, abs=100)


def test_write_wav_roundtrip(tmp_path):
    audio = np.zeros((2, 1000), dtype=np.float32)
    target = tmp_path / "out.wav"
    write_wav(target, audio, 44100)
    info = probe(target)
    assert info.channels == 2
    assert info.duration == pytest.approx(1000 / 44100, abs=1e-4)


def test_decode_same_input_and_output_path(tmp_path):
    source = tmp_path / "source.wav"
    sr = 48000
    t = np.arange(sr, dtype=np.float32) / sr
    stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)], axis=1)
    sf.write(str(source), stereo, sr)

    decode_to_wav(source, source, sample_rate=44100, channels=1)

    info = probe(source)
    assert info.sample_rate == 44100
    assert info.channels == 1
    assert info.duration == pytest.approx(1.0, abs=0.02)
