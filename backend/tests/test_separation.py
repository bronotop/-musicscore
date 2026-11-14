from __future__ import annotations

from pathlib import Path

import pytest

from app.models.adapters import separation


def test_quality_hybrid_prefers_ft_for_core_and_keeps_6s_guitar(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_run(audio_path, raw_output_dir, stems_dir, models_dir, model, preset, log):
        calls.append(model)
        if "6s" in model:
            return {
                "vocals": tmp_path / "vocals-6s.wav",
                "guitar": tmp_path / "guitar-6s.wav",
            }
        return {"vocals": tmp_path / "vocals-ft.wav"}

    monkeypatch.setattr(separation, "_run_model", fake_run)

    mapping, model = separation._separate_quality_hybrid(
        tmp_path / "source.wav",
        tmp_path / "raw",
        tmp_path / "stems",
        tmp_path / "models",
        lambda *_: None,
    )

    assert calls == ["htdemucs_6s.yaml", "htdemucs_ft.yaml"]
    assert model == "htdemucs_6s+htdemucs_ft"
    assert mapping["vocals"].name == "vocals-ft.wav"
    assert mapping["guitar"].name == "guitar-6s.wav"


def test_demucs_quality_uses_shift_trick_defaults(monkeypatch):
    pytest.importorskip("audio_separator")
    quality = separation._separator_kwargs(Path("."), Path("."), "quality")
    fast = separation._separator_kwargs(Path("."), Path("."), "fast")
    assert quality["demucs_params"]["shifts"] == 4
    assert quality["demucs_params"]["overlap"] == 0.5
    assert fast["demucs_params"]["shifts"] == 1
    assert fast["demucs_params"]["overlap"] == 0.25

    monkeypatch.setenv("DEMUCS_SHIFTS", "3")
    monkeypatch.setenv("DEMUCS_OVERLAP", "0.5")
    custom = separation._separator_kwargs(Path("."), Path("."), "fast")
    assert custom["demucs_params"]["shifts"] == 3
    assert custom["demucs_params"]["overlap"] == 0.5
