"""FastAPI backend for the local music2score web app."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import PROJECT_ROOT, SETTINGS
from app.instruments import REGISTRY
from app.types import STEMS

SETTINGS.ensure_dirs()
PROJECTS_DIR = SETTINGS.projects_dir
JOB_PROCESSES: dict[str, subprocess.Popen] = {}

app = FastAPI(title="music2score", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    preset: str = "fast"
    force: bool = False
    only: list[str] | None = None
    mode: str | None = None
    instrument_id: str | None = None


class TrackPatch(BaseModel):
    instrument_id: str | None = None
    display_name: str | None = None
    delete: bool = False


VALID_MODES = {"full", "solo"}
MAX_TRACK_DISPLAY_NAME = 80


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, max_length: int = 48) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-")
    return (cleaned[:max_length] or "project").lower()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp.replace(path)


def normalize_mode(mode: str | None, instrument_id: str | None) -> tuple[str, str | None]:
    """Validate the project mode and registry instrument id."""
    value = (mode or "full").strip().lower()
    if value not in VALID_MODES:
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'solo'")
    instrument = (instrument_id or "").strip() or None
    if instrument:
        profile = REGISTRY.get(instrument)
        if profile is None:
            raise HTTPException(
                status_code=400, detail=f"unknown instrument_id: {instrument}"
            )
        instrument = profile.id
    if value == "solo" and not instrument:
        raise HTTPException(
            status_code=400, detail="solo mode requires instrument_id"
        )
    return value, instrument


def project_root(project_id: str) -> Path:
    # Project ids are derived from user file names and may contain Chinese.
    if project_id in {".", ".."} or not re.fullmatch(r"[\w.-]+", project_id):
        raise HTTPException(status_code=400, detail="invalid project id")
    projects_dir = PROJECTS_DIR.resolve()
    root = (projects_dir / project_id).resolve()
    if not root.is_relative_to(projects_dir) or root == projects_dir or not root.is_dir():
        raise HTTPException(status_code=404, detail="project not found")
    return root


def safe_file(project_id: str, relative: str) -> Path:
    root = project_root(project_id)
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=403, detail="path escapes project")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return path


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def doctor_info() -> dict:
    from app.services.audio import ffmpeg_version, free_space_gb
    from app.services.notation import find_musescore

    info: dict[str, Any] = {
        "home": str(SETTINGS.home),
        "python": sys.version.split()[0],
        "free_space_gb": round(free_space_gb(SETTINGS.home), 1),
        "ffmpeg": ffmpeg_version(),
        "musescore": str(find_musescore(SETTINGS.musescore_path) or ""),
        "packages": {},
        "torch": None,
        "cuda": False,
        "gpu": None,
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = bool(torch.cuda.is_available())
        if info["cuda"]:
            props = torch.cuda.get_device_properties(0)
            info["gpu"] = f"{props.name} ({props.total_memory / 1024**3:.1f} GB)"
    except Exception as exc:  # pragma: no cover - diagnostic
        info["torch_error"] = str(exc)
    for name in (
        "audio_separator",
        "basic_pitch",
        "transkun",
        "beat_this",
        "muscriptor",
        "adtof_pytorch",
        "verovio",
        "faster_whisper",
    ):
        info["packages"][name] = module_available(name)
    try:
        from app.models.adapters.muscriptor import locate_weights

        weights = locate_weights()
        info["muscriptor_weights"] = str(weights) if weights else ""
    except Exception:
        info["muscriptor_weights"] = ""
    try:
        from app.models.adapters.lyrics import locate_model

        model = locate_model()
        info["lyrics_model"] = str(model) if model else ""
    except Exception:
        info["lyrics_model"] = ""
    try:
        from app.models.adapters.game import locate_model as locate_game

        game_model = locate_game()
        info["game_model"] = str(game_model) if game_model else ""
    except Exception:
        info["game_model"] = ""
    return info


def project_payload(project_id: str) -> dict:
    root = project_root(project_id)
    meta = read_json(root / "project.json", {})
    analysis = read_json(root / "analysis.json", {})
    run = read_json(root / "run.json", {})
    job = read_json(root / "job.json", None)
    if job is None:
        # CLI-created projects have run.json but no worker job.json.
        job = (
            {"status": "done", "progress": 100, "message": "done"}
            if run
            else {"status": "idle", "progress": 0}
        )
    tracks = read_json(root / "midi" / "final" / "tracks.json", {"tracks": []})
    track_list = tracks.get("tracks", [])
    for track in track_list:
        if not isinstance(track, dict):
            continue
        if not track.get("audio"):
            track["audio"] = _track_audio_rel(
                root,
                str(track.get("stem") or ""),
                track.get("instrument_id"),
                track,
            )

    stems = sorted(
        path.stem for path in (root / "stems").glob("*.wav") if path.is_file()
    )
    files: list[str] = []
    for sub in ("midi/final", "score", "exports"):
        directory = root / sub
        if directory.exists():
            files.extend(
                path.relative_to(root).as_posix()
                for path in sorted(directory.rglob("*"))
                if path.is_file()
            )

    return {
        "project": meta,
        "job": job,
        "analysis": analysis,
        "run": run,
        "tracks": track_list,
        "stems": stems,
        "manual_stems": _manual_stem_ids(meta),
        "files": files,
        "source_audio": f"/api/projects/{project_id}/source",
    }


def spawn_worker(
    project_id: str,
    preset: str,
    force: bool,
    only: list[str] | None = None,
) -> None:
    existing = JOB_PROCESSES.get(project_id)
    if existing is not None and existing.poll() is None:
        raise HTTPException(status_code=409, detail="a job is already running for this project")

    root = project_root(project_id)
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["MUSIC2SCORE_HOME"] = str(SETTINGS.home)
    env["PYTHONPATH"] = str(backend_dir) + os.pathsep + env.get("PYTHONPATH", "")

    command = [
        sys.executable,
        "-m",
        "app.worker",
        "--project-dir",
        str(root),
        "--preset",
        preset,
    ]
    if force:
        command.append("--force")
    if only:
        command.extend(["--only", ",".join(only)])

    worker_log = (root / "worker.out").open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(backend_dir),
        env=env,
        stdout=worker_log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    JOB_PROCESSES[project_id] = process


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "music2score"}


@app.get("/api/instruments")
def list_instruments() -> dict:
    return {"instruments": [profile.to_dict() for profile in REGISTRY.all()]}


@app.get("/api/doctor")
def doctor() -> dict:
    return doctor_info()


@app.get("/api/projects")
def list_projects() -> dict:
    projects = []
    if PROJECTS_DIR.exists():
        for root in sorted(PROJECTS_DIR.iterdir(), reverse=True):
            if not root.is_dir():
                continue
            meta = read_json(root / "project.json")
            if not meta:
                continue
            job = read_json(root / "job.json", None)
            if job is None:
                job = (
                    {"status": "done", "progress": 100}
                    if (root / "run.json").exists()
                    else {"status": "idle", "progress": 0}
                )
            projects.append(
                {
                    "project_id": root.name,
                    "title": meta.get("title") or root.name,
                    "source": meta.get("original_filename", ""),
                    "created_at": meta.get("created_at", ""),
                    "status": job.get("status", "idle"),
                    "progress": job.get("progress", 0),
                }
            )
    return {"projects": projects}


@app.post("/api/projects")
async def create_project(
    file: UploadFile = File(...),
    preset: str = Form("fast"),
    title: str = Form(""),
    start: bool = Form(True),
    mode: str = Form("full"),
    instrument_id: str = Form(""),
) -> dict:
    mode, instrument_id = normalize_mode(mode, instrument_id)
    original = Path(file.filename or "upload.wav")
    extension = original.suffix.lower() or ".wav"
    project_id = f"{datetime.now():%Y%m%d-%H%M%S}_{slugify(original.stem)}"
    root = PROJECTS_DIR / project_id
    root.mkdir(parents=True, exist_ok=False)

    source_path = root / f"source{extension}"
    with source_path.open("wb") as handle:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)

    meta = {
        "project_id": project_id,
        "title": title or original.stem,
        "original_filename": original.name,
        "source_path": str(source_path),
        "preset": preset,
        "mode": mode,
        "created_at": utcnow(),
    }
    if instrument_id:
        meta["instrument_id"] = instrument_id
    write_json_atomic(root / "project.json", meta)

    if start:
        spawn_worker(project_id, preset, force=False)

    return project_payload(project_id)


def _kill_process_tree(pid: int) -> None:
    """Stop a worker and its interpreter trampoline children."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """Delete a project directory, stopping its worker first."""
    root = project_root(project_id)

    process = JOB_PROCESSES.pop(project_id, None)
    if process is not None and process.poll() is None:
        _kill_process_tree(process.pid)

    # The API may have been restarted since the job started, so also stop the
    # pid recorded in job.json.
    job = read_json(root / "job.json", {})
    worker_pid = job.get("pid")
    if (
        job.get("status") == "running"
        and isinstance(worker_pid, int)
        and worker_pid != os.getpid()
    ):
        _kill_process_tree(worker_pid)

    for attempt in range(6):
        try:
            shutil.rmtree(root)
            break
        except FileNotFoundError:
            break
        except OSError as exc:
            if attempt == 5:
                raise HTTPException(
                    status_code=500,
                    detail=f"项目文件仍被占用，请稍后重试：{exc}",
                ) from exc
            time.sleep(0.5)

    return {"status": "deleted", "project_id": project_id}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return project_payload(project_id)


@app.post("/api/projects/{project_id}/run")
def run_project(project_id: str, request: RunRequest) -> dict:
    root = project_root(project_id)
    meta = read_json(root / "project.json", {})
    meta["preset"] = request.preset
    if request.mode is not None or request.instrument_id is not None:
        mode, instrument_id = normalize_mode(
            request.mode if request.mode is not None else meta.get("mode", "full"),
            request.instrument_id
            if request.instrument_id is not None
            else meta.get("instrument_id"),
        )
        meta["mode"] = mode
        if instrument_id:
            meta["instrument_id"] = instrument_id
        else:
            meta.pop("instrument_id", None)
    write_json_atomic(root / "project.json", meta)
    (root / "job.json").unlink(missing_ok=True)
    spawn_worker(project_id, request.preset, force=request.force, only=request.only)
    return {"status": "running", "project_id": project_id}


@app.get("/api/projects/{project_id}/job")
def job_status(project_id: str) -> dict:
    root = project_root(project_id)
    return read_json(root / "job.json", {"status": "idle"})


@app.get("/api/projects/{project_id}/log")
def job_log(project_id: str, lines: int = 300) -> dict:
    root = project_root(project_id)
    path = root / "job.log"
    if not path.exists():
        return {"lines": []}
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"lines": content[-max(1, min(lines, 2000)):]}


def _manual_stem_ids(meta: dict) -> list[str]:
    ids: list[str] = []
    for item in meta.get("manual_stems") or []:
        if isinstance(item, dict):
            item = item.get("instrument_id")
        value = str(item or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def _track_midi_path(root: Path, stem: str, previous: dict) -> str:
    previous_midi = str(previous.get("midi") or "").strip()
    if previous_midi and (root / previous_midi).is_file():
        return previous_midi
    if re.fullmatch(r"[A-Za-z0-9 _.()-]+", stem or ""):
        candidate = root / "midi" / "final" / f"{stem}.mid"
        if candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return "midi/final/full.mid"


def _track_audio_rel(
    root: Path,
    stem: str,
    instrument_id: str | None,
    previous: dict | None = None,
) -> str | None:
    """Resolve a track's audible stem file, if it has one."""
    previous = previous or {}
    previous_audio = str(previous.get("audio") or "").strip()
    if previous_audio and (root / previous_audio).is_file():
        return previous_audio
    midi_name = Path(str(previous.get("midi") or "")).stem
    for name in (midi_name, stem, instrument_id):
        value = str(name or "").strip()
        if not value:
            continue
        candidate = root / "stems" / f"{value}.wav"
        if candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return None


def _sync_track_midi_files(root: Path, tracks: list[dict]) -> None:
    """Rewrite each per-track MIDI from full.mid after instrument/name edits."""
    full_path = root / "midi" / "final" / "full.mid"
    if not full_path.is_file():
        return
    try:
        import pretty_midi

        full = pretty_midi.PrettyMIDI(str(full_path))
    except Exception:
        return
    if not full.instruments:
        return
    tempo_changes = full.get_tempo_changes()
    tempo = float(tempo_changes[1][0]) if len(tempo_changes[1]) else 120.0
    root_resolved = root.resolve()
    for index, track in enumerate(tracks):
        if index >= len(full.instruments):
            break
        rel = str(track.get("midi") or "").strip()
        if not rel or rel == "midi/final/full.mid":
            continue
        target = (root / rel).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            continue
        source = full.instruments[index]
        midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
        copied = pretty_midi.Instrument(
            program=int(source.program),
            is_drum=bool(source.is_drum),
            name=str(
                track.get("display_name")
                or source.name
                or track.get("stem")
                or "track"
            ),
        )
        copied.notes = [
            pretty_midi.Note(
                velocity=int(note.velocity),
                pitch=int(note.pitch),
                start=float(note.start),
                end=float(note.end),
            )
            for note in source.notes
        ]
        midi.instruments.append(copied)
        target.parent.mkdir(parents=True, exist_ok=True)
        midi.write(str(target))


def rebuild_tracks(
    root: Path,
    midi_path: Path,
    overrides: dict[int, dict] | None = None,
) -> list[dict]:
    """Regenerate tracks.json after the user edits full.mid.

    Existing metadata is preserved by track name first and by index second so
    user-assigned instrument ids and display names survive a save.  Missing
    fields are derived from the instrument registry; output is additive to the
    historical ``stem/program/is_drum/notes`` contract.
    """
    import pretty_midi

    root = Path(root)
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    meta = read_json(root / "project.json", {})
    manual_stems = _manual_stem_ids(meta)
    project_mode = str(meta.get("mode") or "full")
    tracks_path = root / "midi" / "final" / "tracks.json"
    previous_tracks = read_json(tracks_path, {}).get("tracks", [])
    previous_by_name: dict[str, dict] = {}
    for item in previous_tracks:
        for key in (
            item.get("stem"),
            item.get("display_name"),
            item.get("instrument_id"),
        ):
            normalized = str(key or "").strip().lower()
            if normalized:
                previous_by_name.setdefault(normalized, item)

    overrides = overrides or {}
    tracks: list[dict] = []
    used_previous: set[int] = set()
    for index, instrument in enumerate(midi.instruments):
        label = (instrument.name or "").strip() or (
            "drums" if instrument.is_drum else f"program_{instrument.program}"
        )
        previous = previous_by_name.get(label.lower())
        if previous is not None and id(previous) in used_previous:
            previous = None
        if previous is None and index < len(previous_tracks):
            candidate = previous_tracks[index]
            if id(candidate) not in used_previous:
                previous = candidate
        previous = previous or {}
        if previous:
            used_previous.add(id(previous))
        override = overrides.get(index) or {}

        previous_id = previous.get("instrument_id")
        profile = REGISTRY.get(override.get("instrument_id") or previous_id)
        if profile is None:
            profile = REGISTRY.resolve(label, instrument.program, default=True)

        if override.get("instrument_id") and override["instrument_id"] != previous_id:
            display_name = (
                str(override.get("display_name") or "").strip() or profile.name_en
            )
        else:
            display_name = (
                str(override.get("display_name") or "").strip()
                or str(previous.get("display_name") or "").strip()
                or profile.name_en
            )

        stem = str(previous.get("stem") or "").strip() or label
        if override.get("instrument_id") and override["instrument_id"] != previous_id:
            stem = label

        if previous.get("source"):
            source = str(previous["source"])
        elif profile.id in manual_stems:
            source = "manual"
        elif project_mode == "solo":
            source = "solo"
        elif stem in STEMS:
            source = "core"
        else:
            source = "extra"

        entry = {
            "stem": stem,
            "instrument_id": profile.id,
            "display_name": display_name,
            "program": int(instrument.program),
            "is_drum": bool(instrument.is_drum),
            "notes": len(instrument.notes),
            "source": source,
            "midi": _track_midi_path(root, stem, previous),
            "audio": _track_audio_rel(root, stem, profile.id, previous),
            "clef": profile.clef,
            "transpose": int(profile.transpose),
        }
        if previous.get("confidence") is not None:
            entry["confidence"] = previous["confidence"]
        if previous.get("model"):
            entry["model"] = previous["model"]
        tracks.append(entry)

    bpm = 120.0
    try:
        changes = midi.get_tempo_changes()
        if len(changes[1]):
            bpm = round(float(changes[1][0]), 2)
    except Exception:
        pass

    write_json_atomic(tracks_path, {"tracks": tracks, "bpm": bpm})
    return tracks


@app.put("/api/projects/{project_id}/midi/final/{filename}")
async def save_final_midi(project_id: str, filename: str, request: Request) -> dict:
    if Path(filename).name != filename or not filename.endswith(".mid"):
        raise HTTPException(status_code=400, detail="invalid MIDI filename")

    root = project_root(project_id)
    target = (root / "midi" / "final" / filename).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=403, detail="path escapes project")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty MIDI body")
    if len(body) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="MIDI larger than 20 MB")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{filename}.{uuid4().hex}.tmp")
    temp.write_bytes(body)
    try:
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(str(temp))
        if not any(instrument.notes for instrument in midi.instruments):
            raise ValueError("MIDI contains no notes")
    except Exception as exc:
        temp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"invalid MIDI: {exc}") from exc

    temp.replace(target)
    tracks = rebuild_tracks(root, target)
    _sync_track_midi_files(root, tracks)
    return {
        "status": "saved",
        "notes": sum(track["notes"] for track in tracks),
        "tracks": tracks,
    }


def _write_midi_atomic(midi: Any, target: Path) -> None:
    temp = target.with_name(f".{target.stem}.{uuid4().hex}.mid")
    midi.write(str(temp))
    temp.replace(target)


def _trigger_notate(project_id: str, root: Path) -> None:
    meta = read_json(root / "project.json", {})
    (root / "job.json").unlink(missing_ok=True)
    spawn_worker(project_id, meta.get("preset", "fast"), force=True, only=["notate"])


@app.patch("/api/projects/{project_id}/tracks/{index}")
def update_track(project_id: str, index: int, patch: TrackPatch) -> dict:
    """Change instrument / display name or remove one track of full.mid."""
    root = project_root(project_id)
    midi_path = root / "midi" / "final" / "full.mid"
    if not midi_path.is_file():
        raise HTTPException(status_code=404, detail="full.mid not found")

    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(midi_path))
    if index < 0 or index >= len(midi.instruments):
        raise HTTPException(status_code=404, detail="track index out of range")
    if patch.delete and len(midi.instruments) <= 1:
        raise HTTPException(status_code=400, detail="cannot delete the last track")

    tracks = read_json(root / "midi" / "final" / "tracks.json", {}).get("tracks", [])
    if len(tracks) != len(midi.instruments):
        tracks = rebuild_tracks(root, midi_path)
    previous = tracks[index] if index < len(tracks) else {}

    if patch.delete:
        midi.instruments.pop(index)
        _write_midi_atomic(midi, midi_path)
        tracks = rebuild_tracks(root, midi_path)
        _sync_track_midi_files(root, tracks)
        _trigger_notate(project_id, root)
        return {"status": "deleted", "tracks": tracks}

    instrument = midi.instruments[index]
    if patch.instrument_id is not None:
        profile = REGISTRY.get(patch.instrument_id.strip())
        if profile is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown instrument_id: {patch.instrument_id}",
            )
    else:
        profile = REGISTRY.get(previous.get("instrument_id"))
        if profile is None:
            profile = REGISTRY.resolve(
                instrument.name, instrument.program, default=True
            )

    if patch.display_name is not None:
        display_name = patch.display_name.strip() or profile.name_en
    elif patch.instrument_id is not None and previous.get("instrument_id") != profile.id:
        display_name = profile.name_en
    else:
        display_name = (
            str(previous.get("display_name") or "").strip() or profile.name_en
        )
    if len(display_name) > MAX_TRACK_DISPLAY_NAME:
        raise HTTPException(status_code=400, detail="display_name is too long")

    instrument.name = display_name
    instrument.program = int(profile.gm_program)
    instrument.is_drum = profile.notation == "percussion"

    _write_midi_atomic(midi, midi_path)
    tracks = rebuild_tracks(
        root,
        midi_path,
        overrides={
            index: {"instrument_id": profile.id, "display_name": display_name}
        },
    )
    _sync_track_midi_files(root, tracks)
    _trigger_notate(project_id, root)
    return {"status": "updated", "tracks": tracks}


@app.post("/api/projects/{project_id}/stems")
async def upload_manual_stem(
    project_id: str,
    file: UploadFile = File(...),
    instrument_id: str = Form(...),
) -> dict:
    """Accept a user-supplied WAV stem and re-run transcription from it."""
    root = project_root(project_id)
    profile = REGISTRY.get(instrument_id.strip())
    if profile is None:
        raise HTTPException(
            status_code=400, detail=f"unknown instrument_id: {instrument_id}"
        )
    filename = file.filename or ""
    if not filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="only .wav stems are supported")

    target = root / "stems" / f"{profile.id}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{profile.id}.{uuid4().hex}.tmp.wav")
    empty = True
    try:
        with temp.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if empty:
                    if (
                        len(chunk) < 12
                        or chunk[:4] not in (b"RIFF", b"RF64")
                        or chunk[8:12] != b"WAVE"
                    ):
                        raise HTTPException(
                            status_code=400, detail="file is not a valid WAV"
                        )
                    empty = False
                handle.write(chunk)
        if empty:
            raise HTTPException(status_code=400, detail="empty stem file")
        temp.replace(target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

    meta = read_json(root / "project.json", {})
    manual_stems = _manual_stem_ids(meta)
    if profile.id not in manual_stems:
        manual_stems.append(profile.id)
    meta["manual_stems"] = manual_stems
    write_json_atomic(root / "project.json", meta)

    (root / "job.json").unlink(missing_ok=True)
    spawn_worker(
        project_id,
        meta.get("preset", "fast"),
        force=True,
        only=["transcribe", "assemble", "notate"],
    )
    return {
        "status": "running",
        "instrument_id": profile.id,
        "manual_stems": manual_stems,
    }


@app.post("/api/projects/{project_id}/render")
def render_project(project_id: str) -> dict:
    root = project_root(project_id)
    meta = read_json(root / "project.json", {})
    (root / "job.json").unlink(missing_ok=True)
    spawn_worker(
        project_id,
        meta.get("preset", "quality"),
        force=True,
        only=["notate"],
    )
    return {"status": "running", "project_id": project_id}


@app.websocket("/api/projects/{project_id}/events")
async def project_events(websocket: WebSocket, project_id: str) -> None:
    await websocket.accept()
    root = PROJECTS_DIR / project_id
    last: str | None = None
    try:
        while True:
            payload = read_json(root / "job.json", {"status": "idle"})
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if serialized != last:
                await websocket.send_json(payload)
                last = serialized
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/projects/{project_id}/source")
def get_source_audio(project_id: str) -> FileResponse:
    """Serve the canonical in-project WAV for score-follow playback."""
    root = project_root(project_id)
    resolved = root / "source.wav"
    if not resolved.is_file():
        meta = read_json(root / "project.json", {})
        raw = meta.get("source_path")
        if not raw:
            raise HTTPException(status_code=404, detail="source audio not found")
        try:
            candidate = Path(raw).resolve()
            candidate.relative_to(root.resolve())
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="source audio not found")
        resolved = candidate
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="source audio not found")
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(resolved, media_type=media_type, filename=resolved.name)


@app.get("/api/projects/{project_id}/files/{relative:path}")
def get_file(project_id: str, relative: str) -> FileResponse:
    path = safe_file(project_id, relative)
    media_type = None
    if path.suffix == ".musicxml":
        media_type = "application/vnd.recordare.musicxml+xml"
    elif path.suffix == ".mid":
        media_type = "audio/midi"
    elif path.suffix == ".wav":
        media_type = "audio/wav"
    elif path.suffix == ".svg":
        media_type = "image/svg+xml"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/projects/{project_id}/stems/{filename}")
def get_stem(project_id: str, filename: str) -> FileResponse:
    if not filename.endswith(".wav"):
        raise HTTPException(status_code=400, detail="stem filename must end with .wav")
    return get_file(project_id, f"stems/{filename}")


@app.get("/api/projects/{project_id}/midi/{scope}/{name}")
def get_midi(project_id: str, scope: str, name: str) -> FileResponse:
    if scope not in ("model", "final"):
        raise HTTPException(status_code=400, detail="scope must be model or final")
    return get_file(project_id, f"midi/{scope}/{name}")


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:

    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "music2score",
                "docs": "/docs",
                "message": "Run the Vite frontend on :5173, or build it into frontend/dist.",
            }
        )
