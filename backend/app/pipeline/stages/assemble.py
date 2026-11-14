"""Quantize per-stem notes to the beat grid and merge into a multi-track MIDI."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np

from app.instruments import REGISTRY
from app.models.adapters.common import note_events_to_midi
from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult
from app.services.fusion import (
    EvidenceIndex,
    aggregate_stats,
    dedupe_quantized,
    enforce_quantized_limits,
    fuse_notes,
    profile_for,
    profile_from_instrument,
)
from app.services.quantize import BeatGridQuantizer, regular_beats
from app.types import DRUM_GM_MAP, STEMS, NoteEvent, relpath

# Core instruments already covered by dedicated stems: piano 0-7, guitar 24-31,
# bass 32-39, voice 52-54. MuScriptor full-mix tracks in these families would
# duplicate the stem tracks, so only its remaining instruments are added.
CORE_PROGRAMS = set(range(0, 8)) | set(range(24, 40)) | set(range(52, 55))
MAX_MUSCRIPTOR_TRACKS = 12

# Brass, reed and pipe instruments are monophonic; MuScriptor sometimes emits
# chord stacks for them. Keep one note per onset so the score stays readable.
MONOPHONIC_PROGRAMS = set(range(56, 80))

# MuScriptor sometimes emits near-empty or doubled extra tracks. These
# conservative thresholds keep real counter-melodies while dropping noise.
MIN_EXTRA_NOTES = 4
MIN_EXTRA_DENSITY = 0.012  # notes per second
MIN_EXTRA_ENERGY_RATIO = 0.005  # relative to the strongest extra track
DUPLICATE_WINDOW = 0.06  # seconds
DUPLICATE_RATIO = 0.7  # fraction of notes that must coincide


def _energy(notes: list[NoteEvent]) -> float:
    return sum(
        max(0.0, note.end - note.start) * max(1, note.velocity) / 127.0
        for note in notes
    )


def _duplicate_ratio(
    candidate: list[NoteEvent],
    reference: list[NoteEvent],
    window: float = DUPLICATE_WINDOW,
) -> float:
    """Fraction of candidate notes with a same-pitch note in *reference*."""
    if not candidate or not reference:
        return 0.0
    ordered = sorted(reference, key=lambda note: note.start)
    starts = np.asarray([note.start for note in ordered], dtype=float)
    pitches = np.asarray([note.pitch for note in ordered], dtype=int)
    matched = 0
    for note in candidate:
        left = int(np.searchsorted(starts, note.start - window, side="left"))
        right = int(np.searchsorted(starts, note.start + window, side="right"))
        if right > left and bool(np.any(pitches[left:right] == note.pitch)):
            matched += 1
    return matched / len(candidate)


def _normalized_label(name: str) -> str:
    label = name.strip().lower()
    if label.startswith("muscriptor_"):
        label = label[len("muscriptor_"):]
    return re.sub(r"[\s_\-#]*\d+$", "", label)


def _dedupe_notes(notes: list[NoteEvent]) -> list[NoteEvent]:
    seen: set[tuple[int, int, int]] = set()
    unique: list[NoteEvent] = []
    for note in sorted(notes, key=lambda item: (item.start, item.pitch)):
        key = (note.pitch, round(note.start, 3), round(note.end, 3))
        if key in seen:
            continue
        seen.add(key)
        unique.append(note)
    return unique


def _thin_monophonic(
    notes: list[NoteEvent], group_window: float = 0.06
) -> list[NoteEvent]:
    """Keep one note per onset and remove overlaps for a solo instrument."""
    if not notes:
        return []
    ordered = sorted(notes, key=lambda item: (item.start, -item.velocity, item.pitch))
    groups: list[list[NoteEvent]] = []
    current: list[NoteEvent] = []
    for note in ordered:
        if current and abs(note.start - current[0].start) <= group_window:
            current.append(note)
        else:
            if current:
                groups.append(current)
            current = [note]
    if current:
        groups.append(current)

    chosen = [max(group, key=lambda item: (item.velocity, item.pitch)) for group in groups]
    chosen.sort(key=lambda item: item.start)
    result: list[NoteEvent] = []
    for note in chosen:
        if note.end <= note.start:
            continue
        if result and note.start < result[-1].end:
            result[-1].end = max(result[-1].start + 0.01, note.start)
        result.append(note)
    return result


def _select_extra_tracks(
    candidates: list[dict],
    core_notes: list[NoteEvent],
    duration: float,
    log,
) -> tuple[list[dict], list[dict]]:
    """Drop duplicates / noise from MuScriptor's extra instrument tracks."""
    filtered: list[dict] = []
    unique: list[dict] = []

    for candidate in sorted(
        candidates, key=lambda item: len(item["notes"]), reverse=True
    ):
        reason = None
        if _duplicate_ratio(candidate["notes"], core_notes) >= DUPLICATE_RATIO:
            reason = "duplicates core stem"
        else:
            for other in unique:
                if (
                    _duplicate_ratio(candidate["notes"], other["notes"])
                    >= DUPLICATE_RATIO
                ):
                    reason = f"duplicates {other['name']}"
                    break
        if reason:
            filtered.append(
                {
                    "name": candidate["name"],
                    "notes": len(candidate["notes"]),
                    "reason": reason,
                }
            )
        else:
            unique.append(candidate)

    merged: dict[str, dict] = {}
    for candidate in unique:
        key = _normalized_label(candidate["name"])
        if key in merged:
            merged[key]["notes"].extend(candidate["notes"])
            merged[key]["notes"] = _dedupe_notes(merged[key]["notes"])
        else:
            merged[key] = {**candidate, "notes": list(candidate["notes"])}
    tracks = list(merged.values())

    max_energy = max((_energy(track["notes"]) for track in tracks), default=0.0)
    selected: list[dict] = []
    for track in sorted(tracks, key=lambda item: _energy(item["notes"]), reverse=True):
        count = len(track["notes"])
        energy = _energy(track["notes"])
        density = count / duration if duration > 0 else 0.0
        reason = None
        if count < MIN_EXTRA_NOTES:
            reason = f"only {count} notes"
        elif re.search(r"program[ _]?\d+", track["name"], re.IGNORECASE) and count < 8:
            reason = "unknown sparse program"
        elif duration > 0 and density < MIN_EXTRA_DENSITY:
            reason = f"sparse ({density:.3f} notes/s)"
        elif max_energy > 0 and energy / max_energy < MIN_EXTRA_ENERGY_RATIO:
            reason = "low energy"
        if reason:
            filtered.append(
                {"name": track["name"], "notes": count, "reason": reason}
            )
            continue
        selected.append(track)
        if len(selected) >= MAX_MUSCRIPTOR_TRACKS:
            break

    if filtered:
        detail = ", ".join(
            f"{item['name']} ({item['reason']})" for item in filtered[:6]
        )
        log(f"    MuScriptor filtered {len(filtered)} track(s): {detail}")
    return selected, filtered



def _load_confidences(path: Path) -> dict[int, list[tuple[float, float]]]:
    """Load a model confidence sidecar keyed by pitch and start time."""
    sidecar = path.with_name(f"{path.stem}.confidence.json")
    mapping: dict[int, list[tuple[float, float]]] = {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return mapping
    for item in data.get("notes", []):
        try:
            pitch = int(item["pitch"])
            start = float(item["start"])
            confidence = max(0.0, min(1.0, float(item.get("confidence", 1.0))))
        except (KeyError, TypeError, ValueError):
            continue
        mapping.setdefault(pitch, []).append((start, confidence))
    for values in mapping.values():
        values.sort()
    return mapping


def _confidence_at(
    mapping: dict[int, list[tuple[float, float]]],
    pitch: int,
    start: float,
    tolerance: float = 0.03,
) -> float:
    values = mapping.get(pitch)
    if not values:
        return 1.0
    best = min(values, key=lambda item: abs(item[0] - start))
    return best[1] if abs(best[0] - start) <= tolerance else 1.0


def _read_notes(path: Path) -> list[NoteEvent]:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(path))
    confidences = _load_confidences(Path(path))
    notes = [
        NoteEvent(
            start=note.start,
            end=note.end,
            pitch=note.pitch,
            velocity=note.velocity,
            confidence=_confidence_at(confidences, note.pitch, note.start),
        )
        for instrument in midi.instruments
        for note in instrument.notes
    ]
    return notes


def _confidence_track(name: str, notes: list[NoteEvent]) -> dict:
    return {
        "stem": name,
        "notes": [
            {
                "start": round(note.start, 4),
                "end": round(note.end, 4),
                "pitch": int(note.pitch),
                "confidence": round(float(note.confidence), 4),
            }
            for note in notes
        ],
    }


def _model_midis(ctx: ProjectContext) -> dict[str, Path]:
    """All model MIDI files except the MuScriptor full-mix intermediate."""
    if ctx.mode == "solo" and ctx.instrument_id:
        profile = REGISTRY.resolve(ctx.instrument_id, default=True)
        path = ctx.midi_model_dir / f"{profile.id}.mid"
        return {profile.id: path} if path.exists() else {}
    files: dict[str, Path] = {}
    for stem in STEMS:
        path = ctx.midi_model_dir / f"{stem}.mid"
        if path.exists():
            files[stem] = path
    for path in sorted(ctx.midi_model_dir.glob("*.mid")):
        name = path.stem
        if name == "muscriptor_mix" or name in files:
            continue
        files[name] = path
    return files


def _safe_midi_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return safe or "track"


def _mean_confidence(notes: list[NoteEvent]) -> float:
    if not notes:
        return 0.0
    return round(
        sum(max(0.0, min(1.0, float(note.confidence))) for note in notes)
        / len(notes),
        4,
    )


def _track_meta_for(
    stem: str,
    profile,
    notes: list[NoteEvent],
    source: str,
    midi_path: Path,
    ctx: ProjectContext,
    *,
    model: str = "",
) -> dict:
    is_drum = stem == "drums" or profile.notation == "percussion"
    audio_path = ctx.stem_path(stem)
    entry = {
        "stem": stem,
        "instrument_id": profile.id,
        "display_name": profile.name_en,
        "program": int(profile.gm_program),
        "is_drum": is_drum,
        "notes": len(notes),
        "source": source,
        "midi": relpath(midi_path, ctx.root),
        "audio": relpath(audio_path, ctx.root) if audio_path.is_file() else None,
        "clef": profile.clef,
        "transpose": int(profile.transpose),
        "confidence": _mean_confidence(notes),
    }
    if model:
        entry["model"] = model
    return entry


def _manual_stem_ids(ctx: ProjectContext) -> set[str]:
    """Instrument ids the user added as extra stem files."""
    try:
        meta = ctx.read_json(ctx.root / "project.json", {})
    except Exception:
        return set()
    raw = meta.get("manual_stems") or []
    ids: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            item = item.get("instrument_id")
        value = str(item or "").strip()
        if value:
            ids.add(value)
    return ids


def _track_source(
    ctx: ProjectContext,
    stem: str,
    profile,
    manual_ids: set[str],
) -> str:
    if ctx.mode == "solo":
        return "solo"
    if stem in STEMS:
        return "core"
    if profile.id in manual_ids or stem in manual_ids:
        return "manual"
    return "extra"


class AssembleStage(Stage):
    name = "assemble"

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        files = list(_model_midis(ctx).values())
        # The full-mix pass still contributes evidence and extra tracks, so it
        # is an input even though it is never assembled as a track itself.
        muscriptor_mix = ctx.midi_model_dir / "muscriptor_mix.mid"
        if muscriptor_mix.exists():
            files.append(muscriptor_mix)
        files.append(ctx.analysis_path)
        return files

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict:
        families = ("vocals", "drums", "bass", "guitar", "piano", "other", "muscriptor")
        return {
            "subdivision": 4,
            "quantize": True,
            "mode": ctx.mode,
            "instrument_id": ctx.instrument_id,
            "stems": sorted(_model_midis(ctx)),
            "fusion": {name: asdict(profile_for(name)) for name in families},
        }

    def execute(self, ctx: ProjectContext, upstream: dict[str, StageResult]):
        import pretty_midi

        analysis = ctx.read_json(ctx.analysis_path, {})
        bpm = float(analysis.get("bpm", 120.0))
        beats = analysis.get("beats") or []
        duration = 0.0
        if sourced := analysis.get("duration"):
            duration = float(sourced)
        if not beats:
            source_info = upstream.get("ingest")
            if source_info and "duration" in source_info.metrics:
                duration = float(source_info.metrics["duration"])
            beats = regular_beats(duration or 300.0, bpm).tolist()

        quantizer = BeatGridQuantizer(beats, subdivision=4)
        quantized: dict[str, list[NoteEvent]] = {}
        track_meta: list[dict] = []
        confidence_tracks: list[dict] = []
        fusion_stats: list[dict] = []

        # MuScriptor's full-mix pass is parsed first: its notes are both
        # extra-track candidates and corroboration evidence for core stems.
        # Core-instrument notes are evidence only and are never re-added.
        candidates: list[dict] = []
        mix_evidence: list[NoteEvent] = []
        muscriptor_mix = ctx.midi_model_dir / "muscriptor_mix.mid"
        if muscriptor_mix.exists():
            try:
                mix_midi = pretty_midi.PrettyMIDI(str(muscriptor_mix))
                max_extra_duration = 4.0 * 60.0 / max(bpm, 1.0)
                for instrument in mix_midi.instruments:
                    if instrument.is_drum:
                        continue
                    raw_notes = [
                        NoteEvent(n.start, n.end, n.pitch, n.velocity, 1.0)
                        for n in instrument.notes
                        if n.end > n.start and 0 <= n.pitch <= 127
                    ]
                    mix_evidence.extend(raw_notes)
                    if instrument.program in CORE_PROGRAMS:
                        continue
                    notes = [
                        NoteEvent(
                            note.start,
                            min(note.end, note.start + max_extra_duration),
                            note.pitch,
                            note.velocity,
                            0.8,
                        )
                        for note in raw_notes
                    ]
                    if len(notes) < 2:
                        continue
                    if instrument.program in MONOPHONIC_PROGRAMS:
                        notes = _thin_monophonic(notes)
                    notes = quantizer.quantize_notes(notes)
                    if not notes:
                        continue
                    label = instrument.name or f"program_{instrument.program}"
                    if label.lower().startswith("muscriptor_"):
                        label = label[len("muscriptor_"):]
                    profile = REGISTRY.resolve(label, instrument.program, default=True)
                    if profile.notation == "none" or profile.family == "effect":
                        continue
                    candidates.append(
                        {
                            "name": f"muscriptor_{label}",
                            "program": int(profile.gm_program),
                            "instrument_id": profile.id,
                            "display_name": profile.name_en,
                            "clef": profile.clef,
                            "transpose": int(profile.transpose),
                            "notes": notes,
                        }
                    )
            except Exception as exc:
                ctx.log(
                    f"    MuScriptor mix tracks skipped: {type(exc).__name__}: {exc}"
                )

        evidence = EvidenceIndex(mix_evidence) if mix_evidence else None
        manual_ids = _manual_stem_ids(ctx)
        transcribe_metrics: dict = {}
        if upstream.get("transcribe") is not None:
            transcribe_metrics = upstream["transcribe"].metrics or {}

        for stem, source in _model_midis(ctx).items():
            profile = REGISTRY.resolve(stem, default=True)
            if profile.notation == "none" or profile.family == "effect":
                ctx.log(f"    skipping non-pitched track {stem}")
                continue
            notes = _read_notes(source)
            notes = [note for note in notes if 0 <= note.pitch <= 127 and note.end > note.start]
            # Fusion runs on the raw model timeline: quantization snaps every
            # note to a grid step and would hide short fragments.
            if stem in STEMS:
                notes, stats = fuse_notes(
                    stem,
                    notes,
                    evidence=None if stem == "drums" else evidence,
                )
            else:
                notes, stats = fuse_notes(
                    stem,
                    notes,
                    profile=profile_from_instrument(profile),
                )
            notes = quantizer.quantize_notes(notes)
            notes, collapsed = dedupe_quantized(notes)
            if collapsed:
                stats["removed"]["same_pitch_duplicate"] += collapsed
            notes, post_stats = enforce_quantized_limits(
                stem,
                notes,
                profile=None if stem in STEMS else profile_from_instrument(profile),
            )
            for reason, count in post_stats["removed"].items():
                stats["removed"][reason] += count
            stats["after"] = len(notes)
            fusion_stats.append(stats)
            if not notes:
                continue
            quantized[stem] = notes

            is_drum = stem == "drums" or profile.notation == "percussion"
            program = 0 if is_drum else int(profile.gm_program)
            track_path = ctx.midi_final_dir / f"{_safe_midi_name(stem)}.mid"
            note_events_to_midi(
                notes,
                track_path,
                program=program,
                is_drum=is_drum,
                bpm=bpm,
                name=stem,
            )
            track_meta.append(
                _track_meta_for(
                    stem,
                    profile,
                    notes,
                    _track_source(ctx, stem, profile, manual_ids),
                    track_path,
                    ctx,
                    model=str((transcribe_metrics.get(stem) or {}).get("model") or ""),
                )
            )
            confidence_tracks.append(_confidence_track(stem, notes))

        if duration <= 0:
            duration = max(
                (
                    note.end
                    for notes in quantized.values()
                    for note in notes
                ),
                default=0.0,
            )
        core_notes = [
            note
            for stem, notes in quantized.items()
            if not (REGISTRY.resolve(stem, default=True).notation == "percussion")
            for note in notes
        ]
        extra_tracks, muscriptor_filtered = _select_extra_tracks(
            candidates, core_notes, duration, ctx.log
        )

        fused_extras: list[dict] = []
        for track in extra_tracks:
            profile = REGISTRY.resolve(
                track.get("instrument_id") or track["name"],
                track.get("program"),
                default=True,
            )
            if profile.notation == "none" or profile.family == "effect":
                continue
            notes, stats = fuse_notes(
                track["name"],
                track["notes"],
                profile=profile_from_instrument(profile),
            )
            fusion_stats.append(stats)
            if notes:
                fused_extras.append(
                    {
                        **track,
                        "program": int(profile.gm_program),
                        "instrument_id": profile.id,
                        "display_name": profile.name_en,
                        "clef": profile.clef,
                        "transpose": int(profile.transpose),
                        "notes": notes,
                    }
                )
        extra_tracks = fused_extras
        if not quantized and not extra_tracks:
            raise RuntimeError("No transcribed MIDI tracks to assemble")

        full = pretty_midi.PrettyMIDI(initial_tempo=bpm)
        signature = str(analysis.get("time_signature", "4/4"))
        try:
            numerator, denominator = (int(part) for part in signature.split("/"))
            full.time_signature_changes.append(pretty_midi.TimeSignature(numerator, denominator, 0.0))
        except (ValueError, TypeError):
            pass

        for stem, notes in quantized.items():
            profile = REGISTRY.resolve(stem, default=True)
            is_drum = profile.notation == "percussion"
            instrument = pretty_midi.Instrument(
                program=0 if is_drum else int(profile.gm_program),
                is_drum=is_drum,
                name=stem,
            )
            for note in notes:
                instrument.notes.append(
                    pretty_midi.Note(
                        velocity=int(np.clip(note.velocity, 1, 127)),
                        pitch=int(note.pitch),
                        start=float(note.start),
                        end=float(note.end),
                    )
                )
            full.instruments.append(instrument)

        for track in extra_tracks:
            name = track["name"]
            notes = track["notes"]
            profile = REGISTRY.resolve(
                track.get("instrument_id") or name,
                track.get("program"),
                default=True,
            )
            is_drum = profile.notation == "percussion"
            program = 0 if is_drum else int(track["program"])
            instrument = pretty_midi.Instrument(
                program=program, is_drum=is_drum, name=name
            )
            for note in notes:
                instrument.notes.append(
                    pretty_midi.Note(
                        velocity=int(np.clip(note.velocity, 1, 127)),
                        pitch=int(note.pitch),
                        start=float(note.start),
                        end=float(note.end),
                    )
                )
            full.instruments.append(instrument)
            track_path = ctx.midi_final_dir / f"{_safe_midi_name(name)}.mid"
            note_events_to_midi(
                notes,
                track_path,
                program=program,
                is_drum=is_drum,
                bpm=bpm,
                name=name,
            )
            track_meta.append(
                _track_meta_for(
                    name,
                    profile,
                    notes,
                    "extra",
                    track_path,
                    ctx,
                    model=str(
                        (transcribe_metrics.get("muscriptor_mix") or {}).get("model")
                        or ""
                    ),
                )
            )
            confidence_tracks.append(_confidence_track(name, notes))

        full_path = ctx.midi_final_dir / "full.mid"
        full.write(str(full_path))
        ctx.write_json(ctx.midi_final_dir / "tracks.json", {"tracks": track_meta, "bpm": bpm})
        ctx.write_json(
            ctx.midi_final_dir / "confidence.json",
            {"tracks": confidence_tracks},
        )

        outputs: dict[str, Path] = {"full": full_path}
        for stem in quantized:
            outputs[stem] = ctx.midi_final_dir / f"{_safe_midi_name(stem)}.mid"
        for track in extra_tracks:
            outputs[track["name"]] = ctx.midi_final_dir / f"{_safe_midi_name(track['name'])}.mid"
        return outputs, {
            "bpm": bpm,
            "time_signature": signature,
            "tracks": len(quantized) + len(extra_tracks),
            "notes": sum(len(notes) for notes in quantized.values())
            + sum(len(track["notes"]) for track in extra_tracks),
            "per_track": track_meta,
            "muscriptor_tracks": len(extra_tracks),
            "muscriptor_notes": sum(len(track["notes"]) for track in extra_tracks),
            "muscriptor_filtered": muscriptor_filtered,
            "fusion": aggregate_stats(fusion_stats),
            "drum_gm_map": DRUM_GM_MAP,
        }
