from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pretty_midi
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main


def wav_bytes(duration: float = 0.05, sample_rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * duration))
    return buffer.getvalue()


def make_project(
    root: Path,
    tracks: tuple[tuple[str, int], ...] = (("piano", 0),),
    *,
    mode: str = "full",
    instrument_id: str | None = None,
    previous_tracks: list[dict] | None = None,
) -> Path:
    (root / "stems").mkdir(parents=True, exist_ok=True)
    (root / "midi" / "final").mkdir(parents=True, exist_ok=True)
    meta: dict = {
        "project_id": root.name,
        "title": root.name,
        "original_filename": "song.wav",
        "preset": "fast",
        "mode": mode,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_path": str(root / "source.wav"),
    }
    if instrument_id:
        meta["instrument_id"] = instrument_id
    (root / "project.json").write_text(json.dumps(meta), encoding="utf-8")

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    for name, program in tracks:
        instrument = pretty_midi.Instrument(program=program, name=name)
        instrument.notes.append(pretty_midi.Note(100, 60, 0.0, 0.5))
        midi.instruments.append(instrument)
    midi.write(str(root / "midi" / "final" / "full.mid"))

    if previous_tracks is not None:
        (root / "midi" / "final" / "tracks.json").write_text(
            json.dumps({"tracks": previous_tracks, "bpm": 120.0}), encoding="utf-8"
        )
    return root


@pytest.fixture()
def projects(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    calls: list[dict] = []

    def fake_spawn(project_id, preset, force, only=None):
        calls.append(
            {
                "project_id": project_id,
                "preset": preset,
                "force": force,
                "only": only,
            }
        )

    monkeypatch.setattr(main, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(main, "spawn_worker", fake_spawn)
    return projects_dir, calls


@pytest.fixture()
def client(projects):
    return TestClient(main.app)


def test_instruments_endpoint_lists_registry(client):
    response = client.get("/api/instruments")
    assert response.status_code == 200
    instruments = response.json()["instruments"]
    assert len(instruments) >= 50
    erhu = next(item for item in instruments if item["id"] == "erhu")
    for key in (
        "id",
        "name_en",
        "name_zh",
        "display_name",
        "family",
        "gm_program",
        "range",
        "clef",
        "transpose",
        "notation",
    ):
        assert key in erhu
    assert erhu["gm_program"] == 110
    assert len(erhu["range"]) == 2


def test_create_project_stores_solo_mode_and_instrument(client, projects):
    projects_dir, calls = projects
    response = client.post(
        "/api/projects",
        data={
            "preset": "fast",
            "title": "Solo",
            "mode": "solo",
            "instrument_id": "erhu",
        },
        files={"file": ("song.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 200
    project_id = response.json()["project"]["project_id"]
    meta = json.loads((projects_dir / project_id / "project.json").read_text("utf-8"))
    assert meta["mode"] == "solo"
    assert meta["instrument_id"] == "erhu"
    assert calls and calls[-1]["only"] is None


def test_create_project_rejects_unknown_mode_and_instrument(client, projects):
    response = client.post(
        "/api/projects",
        data={"mode": "karaoke"},
        files={"file": ("song.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 400

    response = client.post(
        "/api/projects",
        data={"mode": "solo", "instrument_id": "not_an_instrument"},
        files={"file": ("song.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 400


def test_create_project_accepts_unicode_filename(client, projects):
    response = client.post(
        "/api/projects",
        data={"preset": "fast", "title": "中文测试曲"},
        files={"file": ("中文测试曲.flac", wav_bytes(), "audio/flac")},
    )
    assert response.status_code == 200
    project_id = response.json()["project"]["project_id"]
    assert "中文测试曲" in project_id

    detail = client.get(f"/api/projects/{project_id}")
    assert detail.status_code == 200
    assert detail.json()["project"]["title"] == "中文测试曲"


def test_safe_file_rejects_prefix_sibling(projects):
    projects_dir, _ = projects
    (projects_dir / "proj" / "stems").mkdir(parents=True)
    (projects_dir / "proj2").mkdir()
    (projects_dir / "proj2" / "secret.txt").write_text("x", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        main.safe_file("proj", "../proj2/secret.txt")
    assert exc.value.status_code == 403


def test_run_request_updates_project_mode(client, projects):
    projects_dir, calls = projects
    root = make_project(projects_dir / "runme", (("piano", 0),))
    response = client.post(
        "/api/projects/runme/run",
        json={
            "preset": "quality",
            "force": True,
            "mode": "solo",
            "instrument_id": "guzheng",
        },
    )
    assert response.status_code == 200
    meta = json.loads((root / "project.json").read_text("utf-8"))
    assert meta["mode"] == "solo"
    assert meta["instrument_id"] == "guzheng"
    assert meta["preset"] == "quality"
    assert calls[-1]["force"] is True


def test_patch_track_updates_midi_and_metadata(client, projects):
    projects_dir, calls = projects
    root = make_project(
        projects_dir / "patchme", (("piano", 0), ("other", 48))
    )
    response = client.patch(
        "/api/projects/patchme/tracks/0", json={"instrument_id": "erhu"}
    )
    assert response.status_code == 200
    track = response.json()["tracks"][0]
    assert track["instrument_id"] == "erhu"
    assert track["display_name"] == "Erhu"
    assert track["program"] == 110
    assert track["is_drum"] is False
    assert track["clef"] == "treble"
    assert track["source"] == "core"
    assert track["midi"] == "midi/final/full.mid"

    midi = pretty_midi.PrettyMIDI(str(root / "midi" / "final" / "full.mid"))
    assert midi.instruments[0].name == "Erhu"
    assert midi.instruments[0].program == 110
    assert midi.instruments[0].is_drum is False

    stored = json.loads(
        (root / "midi" / "final" / "tracks.json").read_text("utf-8")
    )["tracks"]
    assert stored[0]["instrument_id"] == "erhu"
    assert calls[-1]["only"] == ["notate"]
    assert calls[-1]["force"] is True


def test_patch_track_can_switch_to_percussion_and_rename(client, projects):
    projects_dir, _ = projects
    root = make_project(projects_dir / "drums", (("piano", 0), ("other", 48)))

    response = client.patch(
        "/api/projects/drums/tracks/0", json={"instrument_id": "drums"}
    )
    assert response.status_code == 200
    assert response.json()["tracks"][0]["is_drum"] is True
    midi = pretty_midi.PrettyMIDI(str(root / "midi" / "final" / "full.mid"))
    assert midi.instruments[0].is_drum is True
    assert midi.instruments[0].program == 0

    response = client.patch(
        "/api/projects/drums/tracks/0", json={"display_name": "Lead Kit"}
    )
    assert response.status_code == 200
    assert response.json()["tracks"][0]["display_name"] == "Lead Kit"
    midi = pretty_midi.PrettyMIDI(str(root / "midi" / "final" / "full.mid"))
    assert midi.instruments[0].name == "Lead Kit"


def test_patch_track_validates_requests(client, projects):
    projects_dir, _ = projects
    make_project(projects_dir / "validate", (("piano", 0), ("other", 48)))

    assert (
        client.patch(
            "/api/projects/validate/tracks/9", json={"instrument_id": "erhu"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/api/projects/validate/tracks/0",
            json={"instrument_id": "not_an_instrument"},
        ).status_code
        == 400
    )
    assert (
        client.patch(
            "/api/projects/validate/tracks/0", json={"display_name": "x" * 200}
        ).status_code
        == 400
    )
    assert (
        client.patch("/api/projects/validate/tracks/0", json={}).status_code == 200
    )
    assert (
        client.patch(
            "/api/projects/missing/tracks/0", json={"instrument_id": "erhu"}
        ).status_code
        == 404
    )


def test_delete_track_rejects_last_and_removes_others(client, projects):
    projects_dir, _ = projects
    root_one = make_project(projects_dir / "one", (("piano", 0),))
    response = client.patch("/api/projects/one/tracks/0", json={"delete": True})
    assert response.status_code == 400
    assert len(
        pretty_midi.PrettyMIDI(str(root_one / "midi" / "final" / "full.mid")).instruments
    ) == 1

    root_two = make_project(projects_dir / "two", (("piano", 0), ("guitar", 25)))
    response = client.patch("/api/projects/two/tracks/1", json={"delete": True})
    assert response.status_code == 200
    tracks = response.json()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["instrument_id"] == "piano"
    midi = pretty_midi.PrettyMIDI(str(root_two / "midi" / "final" / "full.mid"))
    assert len(midi.instruments) == 1
    assert midi.instruments[0].name == "piano"


def test_delete_track_keeps_metadata_after_rename(client, projects):
    projects_dir, _ = projects
    make_project(projects_dir / "renamed", (("piano", 0), ("guitar", 25)))
    response = client.patch(
        "/api/projects/renamed/tracks/0", json={"display_name": "Lead"}
    )
    assert response.status_code == 200
    assert response.json()["tracks"][0]["display_name"] == "Lead"

    response = client.patch(
        "/api/projects/renamed/tracks/1", json={"delete": True}
    )
    assert response.status_code == 200
    tracks = response.json()["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["stem"] == "piano"
    assert tracks[0]["instrument_id"] == "piano"
    assert tracks[0]["display_name"] == "Lead"


def test_rebuild_tracks_preserves_user_metadata(projects):
    projects_dir, _ = projects
    root = make_project(
        projects_dir / "preserve",
        (("weird label", 110),),
        mode="solo",
        instrument_id="erhu",
        previous_tracks=[
            {
                "stem": "erhu",
                "instrument_id": "guzheng",
                "display_name": "My Zheng",
                "program": 110,
                "is_drum": False,
                "notes": 1,
                "source": "manual",
                "midi": "midi/final/full.mid",
                "audio": "stems/erhu.wav",
                "confidence": 0.42,
                "model": "test-model",
            }
        ],
    )
    (root / "stems" / "erhu.wav").write_bytes(b"RIFFxxxxWAVE")
    tracks = main.rebuild_tracks(root, root / "midi" / "final" / "full.mid")
    assert len(tracks) == 1
    track = tracks[0]
    assert track["stem"] == "erhu"
    assert track["instrument_id"] == "guzheng"
    assert track["display_name"] == "My Zheng"
    assert track["source"] == "manual"
    assert track["clef"] == "treble"
    assert track["audio"] == "stems/erhu.wav"
    assert track["confidence"] == 0.42
    assert track["model"] == "test-model"


def test_project_payload_backfills_track_audio(projects):
    projects_dir, _ = projects
    root = make_project(
        projects_dir / "backfill",
        (("piano", 0),),
        previous_tracks=[
            {
                "stem": "piano",
                "instrument_id": "piano",
                "display_name": "Piano",
                "program": 0,
                "is_drum": False,
                "notes": 1,
                "source": "core",
                "midi": "midi/final/full.mid",
            }
        ],
    )
    (root / "stems" / "piano.wav").write_bytes(b"RIFFxxxxWAVE")

    payload = main.project_payload("backfill")

    assert payload["tracks"][0]["audio"] == "stems/piano.wav"


def test_rebuild_tracks_derives_solo_metadata(projects):
    projects_dir, _ = projects
    root = make_project(
        projects_dir / "solo",
        (("Erhu", 110),),
        mode="solo",
        instrument_id="erhu",
    )
    tracks = main.rebuild_tracks(root, root / "midi" / "final" / "full.mid")
    track = tracks[0]
    assert track["instrument_id"] == "erhu"
    assert track["display_name"] == "Erhu"
    assert track["source"] == "solo"
    assert track["clef"] == "treble"
    assert track["transpose"] == 0
    assert track["midi"] == "midi/final/full.mid"


def test_manual_stem_upload_saves_file_and_metadata(client, projects):
    projects_dir, calls = projects
    root = make_project(projects_dir / "stems", (("piano", 0),))
    response = client.post(
        "/api/projects/stems/stems",
        data={"instrument_id": "erhu"},
        files={"file": ("my-erhu.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["instrument_id"] == "erhu"
    assert body["manual_stems"] == ["erhu"]
    assert (root / "stems" / "erhu.wav").is_file()

    meta = json.loads((root / "project.json").read_text("utf-8"))
    assert meta["manual_stems"] == ["erhu"]
    assert calls[-1]["only"] == ["transcribe", "assemble", "notate"]
    assert calls[-1]["force"] is True

    detail = client.get("/api/projects/stems").json()
    assert detail["manual_stems"] == ["erhu"]


def test_manual_stem_upload_validates_input(client, projects):
    projects_dir, _ = projects
    make_project(projects_dir / "bad-stem", (("piano", 0),))

    assert (
        client.post(
            "/api/projects/bad-stem/stems",
            data={"instrument_id": "not_an_instrument"},
            files={"file": ("x.wav", wav_bytes(), "audio/wav")},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/projects/bad-stem/stems",
            data={"instrument_id": "erhu"},
            files={"file": ("x.mp3", b"id3", "audio/mpeg")},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/projects/bad-stem/stems",
            data={"instrument_id": "erhu"},
            files={"file": ("x.wav", b"not a wav file", "audio/wav")},
        ).status_code
        == 400
    )


def test_delete_project_removes_directory(client, projects):
    projects_dir, _ = projects
    root = make_project(projects_dir / "todelete", (("piano", 0),))

    response = client.delete("/api/projects/todelete")

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert not root.exists()


def test_delete_project_accepts_unicode_id(client, projects):
    projects_dir, _ = projects
    root = make_project(projects_dir / "删除我", (("piano", 0),))

    response = client.delete("/api/projects/%E5%88%A0%E9%99%A4%E6%88%91")

    assert response.status_code == 200
    assert not root.exists()
