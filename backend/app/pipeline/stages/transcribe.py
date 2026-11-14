"""Transcribe each separated stem into a model MIDI file."""

from __future__ import annotations

import os
from pathlib import Path

from app.instruments import REGISTRY
from app.models.adapters import (
    basic_pitch,
    drums,
    game,
    general,
    lyrics,
    piano,
    pitch,
    solo,
    vocals,
)
from app.models.adapters.common import empty_cuda_cache
from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult
from app.types import STEMS


def _stem_files(ctx: ProjectContext) -> dict[str, Path]:
    """Core stems first, then any catalog-recognised extra stem files."""
    if ctx.mode == "solo" and ctx.instrument_id:
        profile = REGISTRY.resolve(ctx.instrument_id, default=True)
        path = ctx.stem_path(profile.id)
        return {profile.id: path} if path.exists() else {}
    files: dict[str, Path] = {}
    for stem in STEMS:
        path = ctx.stem_path(stem)
        if path.exists():
            files[stem] = path
    for path in sorted(ctx.stems_dir.glob("*.wav")):
        stem = path.stem
        if stem in files:
            continue
        if REGISTRY.resolve(stem) is None:
            continue
        files[stem] = path
    return files


def _write_confidences(ctx: ProjectContext, name: str, notes) -> None:
    """Persist per-note model confidence next to the model MIDI.

    MIDI cannot carry confidence, so the piano roll uses this sidecar to
    highlight uncertain notes. It is advisory: a missing file means 1.0.
    """
    payload = {
        "notes": [
            {
                "start": round(float(note.start), 4),
                "end": round(float(note.end), 4),
                "pitch": int(note.pitch),
                "confidence": round(max(0.0, min(1.0, float(note.confidence))), 4),
            }
            for note in notes
        ]
    }
    try:
        ctx.write_json(ctx.midi_model_dir / f"{name}.confidence.json", payload)
    except Exception:
        pass


class TranscribeStage(Stage):
    name = "transcribe"

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        files = list(_stem_files(ctx).values())
        files.append(ctx.analysis_path)
        if ctx.preset == "quality" and ctx.mode == "full" and ctx.source_wav.exists():
            files.append(ctx.source_wav)
        return files

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict:
        stems = _stem_files(ctx)
        return {
            "preset": ctx.preset,
            "mode": ctx.mode,
            "instrument_id": ctx.instrument_id,
            "stems": sorted(stems),
            "models": {
                "vocals": "game->melody->basic-pitch",
                "piano": "transkun->basic-pitch",
                "drums": "adtof->onset-fallback",
                "bass": "basic-pitch",
                "guitar": "basic-pitch->muscriptor",
                "other": "basic-pitch->muscriptor",
                "solo": "profile->pitch/basic-pitch",
            },
            "vocal_melody": {
                "mode": os.environ.get("VOCAL_MELODY_MODE", "auto"),
                "game": str(game.locate_model() or ""),
            },
            "thresholds": {"onset": 0.5, "frame": 0.3, "min_note_length_ms": 58.0},
            "lyrics_model": str(lyrics.locate_model() or ""),
            "quality_defaults": {
                "game_steps": os.environ.get(
                    "VOCAL_GAME_STEPS", "24" if ctx.preset == "quality" else "8"
                ),
                "game_window": os.environ.get(
                    "VOCAL_GAME_WINDOW_SEC",
                    "60" if ctx.preset == "quality" else "45",
                ),
                "lyrics_beam": os.environ.get(
                    "LYRICS_BEAM_SIZE", "8" if ctx.preset == "quality" else "5"
                ),
                "muscriptor_beam": os.environ.get(
                    "MUSCRIPTOR_BEAM_SIZE", "3" if ctx.preset == "quality" else "1"
                ),
            },
        }

    def execute(self, ctx: ProjectContext, upstream: dict[str, StageResult]):
        analysis = ctx.read_json(ctx.analysis_path, {"bpm": 120.0})
        bpm = float(analysis.get("bpm", 120.0))
        quality = ctx.preset == "quality"

        outputs: dict[str, Path] = {}
        metrics: dict[str, dict] = {}

        stems = _stem_files(ctx)
        units = sum(1 for path in stems.values() if path.exists())
        if ctx.preset == "quality" and ctx.mode == "full":
            units += 1  # optional full-mix MuScriptor pass
        units = max(units, 1)
        done = 0

        def report(message: str | None = None) -> None:
            ctx.report_progress(done / units, message)

        report("transcribing stems")
        for stem, stem_path in stems.items():
            if not stem_path.exists():
                continue

            profile = REGISTRY.resolve(stem, default=True)
            if profile.notation == "none" or profile.family == "effect":
                ctx.log(f"    skipping {stem} (non-pitched effect)")
                done += 1
                report(f"skipped {stem}")
                continue

            out_midi = ctx.midi_model_dir / f"{stem}.mid"
            report(f"transcribing {stem}")
            ctx.log(f"    transcribing {stem}")
            try:
                if stem not in STEMS:
                    notes, model = solo.transcribe(
                        stem_path,
                        out_midi,
                        profile,
                        bpm=bpm,
                        quality=quality,
                    )
                elif stem == "vocals":
                    notes, model = vocals.transcribe(
                        stem_path, out_midi, bpm=bpm, quality=quality
                    )
                elif stem == "piano":
                    try:
                        notes, model = piano.transcribe(stem_path, out_midi)
                    except Exception as exc:
                        ctx.log(f"      transkun unavailable ({exc}); using Basic Pitch")
                        notes, model = basic_pitch.transcribe(
                            stem_path,
                            out_midi,
                            program=0,
                            min_frequency=27.5,
                            max_frequency=4186.0,
                            min_note_length_ms=45.0 if quality else 50.0,
                            onset_threshold=0.42 if quality else 0.5,
                            frame_threshold=0.28 if quality else 0.3,
                            bpm=bpm,
                        )
                        model = f"{model} (transkun-failed)"
                elif stem == "drums":
                    notes, model = drums.transcribe(stem_path, out_midi, bpm=bpm)
                elif stem == "bass":
                    try:
                        notes, model = basic_pitch.transcribe(
                            stem_path,
                            out_midi,
                            program=33,
                            min_frequency=30.0,
                            max_frequency=400.0,
                            min_note_length_ms=55.0 if quality else 58.0,
                            onset_threshold=0.42 if quality else 0.5,
                            frame_threshold=0.28 if quality else 0.3,
                            bpm=bpm,
                        )
                    except Exception:
                        notes, model = pitch.transcribe(
                            stem_path,
                            out_midi,
                            program=33,
                            bpm=bpm,
                            fmin=30.0,
                            fmax=400.0,
                        )
                elif stem == "guitar":
                    notes, model = general.transcribe(
                        stem_path,
                        out_midi,
                        program=25,
                        min_frequency=70.0,
                        max_frequency=1600.0,
                        bpm=bpm,
                        instrument_hint="guitar",
                        quality=quality,
                    )
                else:
                    notes, model = general.transcribe(
                        stem_path,
                        out_midi,
                        program=48,
                        min_frequency=40.0,
                        max_frequency=3000.0,
                        bpm=bpm,
                        instrument_hint="other",
                        quality=quality,
                    )
            except Exception as exc:
                ctx.log(f"      {stem} failed: {type(exc).__name__}: {exc}")
                metrics[stem] = {"error": str(exc)}
                done += 1
                report(f"{stem} failed")
                continue

            outputs[stem] = out_midi
            metrics[stem] = {
                "model": model,
                "notes": len(notes),
                "instrument_id": profile.id,
                "display_name": profile.name_en,
            }
            _write_confidences(ctx, stem, notes)
            if stem == "vocals":
                lyrics_path = ctx.midi_model_dir / "vocals.lyrics.json"
                try:
                    payload, lyrics_model = lyrics.transcribe(
                        stem_path, lyrics_path, quality=quality
                    )
                    word_count = sum(
                        len(segment.get("words") or [])
                        for segment in payload.get("segments", [])
                    )
                    outputs["vocals_lyrics"] = lyrics_path
                    metrics[stem]["lyrics"] = {
                        "model": lyrics_model,
                        "language": payload.get("language"),
                        "words": word_count,
                    }
                    ctx.log(
                        f"      vocals lyrics: {word_count} words "
                        f"({payload.get('language')}, {lyrics_model})"
                    )
                except FileNotFoundError:
                    ctx.log("      vocals lyrics skipped (no faster-whisper model)")
                except Exception as exc:
                    metrics[stem]["lyrics_error"] = str(exc)
                    ctx.log(
                        f"      vocals lyrics failed: {type(exc).__name__}: {exc}"
                    )
            ctx.log(f"      {stem}: {len(notes)} notes ({model})")
            empty_cuda_cache()
            done += 1
            report()

        if not outputs:
            raise RuntimeError("No stems were transcribed; check separation and model installs")

        if ctx.preset == "quality" and ctx.mode == "full":
            report("transcribing full mix with MuScriptor")
            try:
                from app.models.adapters import muscriptor as muscriptor_adapter

                if muscriptor_adapter.locate_weights() is not None:
                    mix_out = ctx.midi_model_dir / "muscriptor_mix.mid"
                    ctx.log("    transcribing full mix with MuScriptor")
                    notes, model = muscriptor_adapter.transcribe(
                        ctx.source_wav,
                        mix_out,
                        instruments=None,
                        quality=quality,
                    )
                    outputs["muscriptor_mix"] = mix_out
                    metrics["muscriptor_mix"] = {"model": model, "notes": len(notes)}
                    _write_confidences(ctx, "muscriptor_mix", notes)
                    ctx.log(f"      muscriptor_mix: {len(notes)} notes ({model})")
            except Exception as exc:
                metrics["muscriptor_mix"] = {"error": str(exc)}
                ctx.log(f"      muscriptor_mix failed: {type(exc).__name__}: {exc}")
            done += 1
            report("MuScriptor done")

        if not outputs:
            raise RuntimeError("No stems or full-mix tracks were transcribed")

        ctx.report_progress(1.0, "transcribed")
        return outputs, metrics
