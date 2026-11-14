"""Model-output fusion and confidence filtering.

Basic Pitch (and, to a lesser degree, MuScriptor) can emit over-dense or
octave-duplicated material. This module cleans a single instrument track:

* per-instrument minimum confidence and minimum duration (short fragments
  only disappear when they are also uncertain, so quiet real notes survive),
* same-pitch overlap de-duplication,
* octave-duplicate merging (configurable winner, default higher confidence),
* local density cap and simultaneous-polyphony cap.

Cross-model corroboration: notes from the MuScriptor full-mix pass are used
as *evidence only*. A stem note that coincides with a MuScriptor note gets a
small confidence bonus, which protects it from the thinning passes. The
MuScriptor core instruments are never re-added as tracks.

The pass must run on the raw model timeline, before beat quantization:
quantization snaps every note to at least one grid step, which hides short
fragments and distorts the density measurement.

Every threshold can be overridden with ``M2S_FUSION_*`` environment variables
(see ``ENV_SETTINGS``); per-instrument overrides use the instrument name,
e.g. ``M2S_FUSION_GUITAR_MIN_CONFIDENCE`` or ``M2S_FUSION_MUSCRIPTOR_MAX_POLYPHONY``.
"""

from __future__ import annotations

import bisect
import heapq
import itertools
import os
import re
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from app.types import NoteEvent


@dataclass(frozen=True)
class FusionProfile:
    """Thresholds applied to one instrument track."""

    min_confidence: float = 0.30
    min_duration: float = 0.060
    short_note_confidence: float = 0.40
    max_polyphony: int = 0  # 0 disables the cap
    density_limit: float = 0.0  # notes per second; 0 disables
    density_window: float = 1.5  # seconds
    octave_merge: bool = True
    octave_policy: str = "confidence"  # confidence | low | high
    octave_window: float = 0.10  # max onset distance for an octave duplicate
    octave_overlap: float = 0.85  # overlap relative to the shorter note
    same_pitch_overlap: float = 0.50
    support_bonus: float = 0.25
    support_tolerance: float = 0.10


# Defaults are deliberately conservative: they remove noise on the dense
# Basic Pitch stems while leaving confident piano/drum/MuScriptor notes alone
# (those models report confidence 1.0, so confidence filters never touch them).
DEFAULT_PROFILES: dict[str, FusionProfile] = {
    "vocals": FusionProfile(
        min_confidence=0.30,
        min_duration=0.055,
        max_polyphony=1,
        # A fast vocal run is ~6-8 notes/s; keep generous headroom so an
        # enhanced melody line is never thinned by the density pass.
        density_limit=12.0,
    ),
    "drums": FusionProfile(
        min_confidence=0.0,
        min_duration=0.0,
        max_polyphony=0,
        density_limit=0.0,
        octave_merge=False,
        same_pitch_overlap=0.9,
    ),
    "bass": FusionProfile(
        min_confidence=0.28,
        min_duration=0.055,
        max_polyphony=1,
        density_limit=6.0,
    ),
    "guitar": FusionProfile(
        min_confidence=0.30,
        min_duration=0.060,
        max_polyphony=4,
        density_limit=7.0,
    ),
    "piano": FusionProfile(
        min_confidence=0.25,
        min_duration=0.030,
        max_polyphony=8,
        density_limit=12.0,
        # Transkun/MuScriptor report confidence 1.0 on piano; octave doubling is
        # idiomatic there, so merging would delete real notes.
        octave_merge=False,
    ),
    "other": FusionProfile(
        min_confidence=0.30,
        min_duration=0.060,
        max_polyphony=6,
        density_limit=9.0,
    ),
    # MuScriptor extra tracks are already monophonically thinned by the time
    # they reach fusion; the caps are a safety net for dense brass/sax runs.
    "muscriptor": FusionProfile(
        min_confidence=0.25,
        min_duration=0.045,
        max_polyphony=4,
        density_limit=8.0,
        octave_merge=False,
    ),
}

GENERIC_PROFILE = FusionProfile(octave_merge=False)

# (attribute, environment suffix, value kind). Every suffix is accepted both
# globally (``M2S_FUSION_<SUFFIX>``) and per instrument
# (``M2S_FUSION_<INSTRUMENT>_<SUFFIX>``); the instrument value wins.
ENV_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("min_confidence", "MIN_CONFIDENCE", "float"),
    ("min_duration", "MIN_DURATION_MS", "ms"),
    ("short_note_confidence", "SHORT_NOTE_CONFIDENCE", "float"),
    ("max_polyphony", "MAX_POLYPHONY", "int"),
    ("density_limit", "DENSITY_LIMIT", "float"),
    ("density_window", "DENSITY_WINDOW", "float"),
    ("octave_merge", "OCTAVE_MERGE", "bool"),
    ("octave_policy", "OCTAVE_POLICY", "str"),
    ("octave_window", "OCTAVE_WINDOW", "float"),
    ("octave_overlap", "OCTAVE_OVERLAP", "float"),
    ("same_pitch_overlap", "SAME_PITCH_OVERLAP", "float"),
    ("support_bonus", "SUPPORT_BONUS", "float"),
    ("support_tolerance", "SUPPORT_TOLERANCE", "float"),
)

REMOVAL_REASONS = (
    "invalid",
    "low_confidence",
    "short_fragment",
    "same_pitch_duplicate",
    "octave_duplicate",
    "density",
    "polyphony",
)

_OCTAVE_POLICIES = {"confidence", "low", "high"}


def _score(note: NoteEvent) -> float:
    return (max(1, int(note.velocity)) / 127.0) * max(0.01, float(note.confidence))


def _overlap_ratio(first: NoteEvent, second: NoteEvent) -> float:
    overlap = min(first.end, second.end) - max(first.start, second.start)
    if overlap <= 0:
        return 0.0
    shorter = min(first.end - first.start, second.end - second.start)
    return overlap / shorter if shorter > 0 else 0.0


def _family(name: str) -> str:
    label = name.strip().lower()
    if label.startswith("muscriptor"):
        return "muscriptor"
    match = re.match(r"[a-z]+", label)
    return match.group(0) if match else label


def _env_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")


def _read_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower()


def _apply_env(
    profile: FusionProfile, keys: Sequence[str], *, include_global: bool
) -> FusionProfile:
    changes: dict[str, object] = {}
    for attribute, suffix, kind in ENV_SETTINGS:
        current = getattr(profile, attribute)
        candidates: list[str] = []
        if include_global:
            candidates.append(f"M2S_FUSION_{suffix}")
        # Family defaults first, exact stem last: the most specific variable wins.
        candidates.extend(f"M2S_FUSION_{key}_{suffix}" for key in reversed(keys))
        value = current
        for variable in candidates:
            if kind == "float":
                value = _read_float(variable, float(value))
            elif kind == "int":
                value = _read_int(variable, int(value))
            elif kind == "ms":
                value = _read_float(variable, float(value) * 1000.0) / 1000.0
            elif kind == "bool":
                value = _read_bool(variable, bool(value))
            else:
                value = _read_str(variable, str(value))
        changes[attribute] = value
    policy = str(changes["octave_policy"]).lower()
    if policy not in _OCTAVE_POLICIES:
        changes["octave_policy"] = profile.octave_policy
    return replace(profile, **changes)  # type: ignore[arg-type]


def profile_from_instrument(instrument) -> FusionProfile:
    """Build a FusionProfile from an InstrumentProfile (catalog-driven tracks)."""
    notation = str(getattr(instrument, "notation", "staff"))
    family = str(getattr(instrument, "family", "other"))
    if notation == "percussion" or family == "percussion":
        return FusionProfile(
            min_confidence=0.0,
            min_duration=0.0,
            short_note_confidence=0.0,
            max_polyphony=0,
            density_limit=0.0,
            octave_merge=False,
            same_pitch_overlap=0.9,
            support_bonus=0.0,
        )
    polyphony = int(getattr(instrument, "max_polyphony", 0) or 0)
    if bool(getattr(instrument, "monophonic", False)):
        polyphony = 1
    return FusionProfile(
        min_confidence=0.25,
        min_duration=0.045,
        short_note_confidence=0.40,
        max_polyphony=polyphony,
        density_limit=0.0,
        octave_merge=False,
        support_bonus=0.0,
    )


def profile_for(name: str) -> FusionProfile:
    """Resolve defaults + environment overrides for one instrument track."""
    family = _family(name)
    base = DEFAULT_PROFILES.get(family, GENERIC_PROFILE)
    keys = [family.upper()]
    normalized = _env_key(name)
    if normalized and normalized not in keys:
        keys.insert(0, normalized)
    return _apply_env(base, keys, include_global=True)


class EvidenceIndex:
    """Coincident notes from another model, used as corroboration only."""

    def __init__(self, notes: Iterable[NoteEvent], tolerance: float = 0.10):
        self.tolerance = float(tolerance)
        grouped: dict[int, list[tuple[float, float, float]]] = {}
        for note in notes:
            if note.end <= note.start:
                continue
            grouped.setdefault(int(note.pitch), []).append(
                (float(note.start), float(note.end), float(note.confidence))
            )
        self._by_pitch = {
            pitch: sorted(values, key=lambda item: item[0])
            for pitch, values in grouped.items()
        }

    def support(self, note: NoteEvent, tolerance: float | None = None) -> float:
        """Weighted evidence confidence for *note*, in [0, 1]."""
        tolerance = self.tolerance if tolerance is None else float(tolerance)
        best = 0.0
        for delta, weight in ((0, 1.0), (-12, 0.35), (12, 0.35), (-24, 0.2), (24, 0.2)):
            values = self._by_pitch.get(int(note.pitch) + delta)
            if not values:
                continue
            low = note.start - tolerance
            high = note.start + tolerance
            start = bisect.bisect_left(values, (low, float("-inf"), float("-inf")))
            for onset, end, confidence in values[start:]:
                if onset > high:
                    break
                if end <= note.start:
                    continue
                best = max(best, confidence * weight)
        return min(1.0, best)


def _apply_support(
    notes: list[NoteEvent],
    evidence: EvidenceIndex | None,
    profile: FusionProfile,
) -> tuple[list[NoteEvent], int]:
    if evidence is None or profile.support_bonus <= 0:
        return notes, 0
    boosted: list[NoteEvent] = []
    supported = 0
    for note in notes:
        strength = evidence.support(note, profile.support_tolerance)
        if strength <= 0:
            boosted.append(note)
            continue
        if strength >= 0.5:
            supported += 1
        if note.confidence < 1.0:
            merged = note.confidence + (1.0 - note.confidence) * profile.support_bonus * strength
            if merged > note.confidence:
                note = replace(note, confidence=min(1.0, merged))
        boosted.append(note)
    return boosted, supported


def _filter_confidence(
    notes: list[NoteEvent], profile: FusionProfile
) -> tuple[list[NoteEvent], dict[str, int]]:
    removed = {"invalid": 0, "low_confidence": 0, "short_fragment": 0}
    kept: list[NoteEvent] = []
    for note in notes:
        if note.end <= note.start or note.pitch < 0 or note.pitch > 127:
            removed["invalid"] += 1
            continue
        if note.confidence + 1e-9 < profile.min_confidence:
            removed["low_confidence"] += 1
            continue
        if (
            profile.min_duration > 0
            and note.end - note.start < profile.min_duration
            and note.confidence + 1e-9 < profile.short_note_confidence
        ):
            removed["short_fragment"] += 1
            continue
        kept.append(note)
    return kept, removed


def _dedupe_same_pitch(
    notes: list[NoteEvent], overlap: float
) -> tuple[list[NoteEvent], int]:
    if overlap <= 0:
        return notes, 0
    grouped: dict[int, list[NoteEvent]] = {}
    for note in notes:
        grouped.setdefault(int(note.pitch), []).append(note)
    kept: list[NoteEvent] = []
    dropped = 0
    for pitch in sorted(grouped):
        group = sorted(grouped[pitch], key=lambda item: (item.start, -_score(item)))
        resolved: list[NoteEvent] = []
        for note in group:
            if resolved and _overlap_ratio(resolved[-1], note) >= overlap:
                dropped += 1
                if _score(note) > _score(resolved[-1]):
                    resolved[-1] = note
                continue
            resolved.append(note)
        kept.extend(resolved)
    return kept, dropped


def _octave_winner(first: NoteEvent, second: NoteEvent, policy: str) -> NoteEvent:
    if policy == "low":
        return first if first.pitch < second.pitch else second
    if policy == "high":
        return first if first.pitch > second.pitch else second
    first_key = (_score(first), first.end - first.start, first.pitch)
    second_key = (_score(second), second.end - second.start, second.pitch)
    return first if first_key >= second_key else second


def _dedupe_octaves(
    notes: list[NoteEvent], profile: FusionProfile
) -> tuple[list[NoteEvent], int]:
    if not profile.octave_merge or profile.octave_overlap <= 0 or len(notes) < 2:
        return notes, 0
    window = max(1e-6, profile.octave_window)
    buckets: dict[int, list[int]] = {}
    ordered = sorted(notes, key=lambda item: (item.start, -_score(item), item.pitch))
    for index, note in enumerate(ordered):
        buckets.setdefault(int(note.start // window), []).append(index)
    dropped: set[int] = set()
    for index, note in enumerate(ordered):
        if index in dropped:
            continue
        bucket = int(note.start // window)
        for neighbor in (bucket - 1, bucket, bucket + 1):
            for other_index in buckets.get(neighbor, ()):
                if other_index <= index or other_index in dropped:
                    continue
                other = ordered[other_index]
                difference = abs(int(other.pitch) - int(note.pitch))
                if difference not in (12, 24):
                    continue
                if abs(other.start - note.start) > profile.octave_window:
                    continue
                if _overlap_ratio(note, other) < profile.octave_overlap:
                    continue
                winner = _octave_winner(note, other, profile.octave_policy)
                dropped.add(other_index if winner is note else index)
                if index in dropped:
                    break
            if index in dropped:
                break
    kept = [note for index, note in enumerate(ordered) if index not in dropped]
    return kept, len(dropped)


def _track_span(notes: list[NoteEvent]) -> float:
    if not notes:
        return 0.0
    return max(note.end for note in notes) - min(note.start for note in notes)


def _cap_density(
    notes: list[NoteEvent], profile: FusionProfile, span: float
) -> tuple[list[NoteEvent], int]:
    limit = profile.density_limit
    window = profile.density_window
    if limit <= 0 or span <= 0 or window <= 0 or len(notes) < 2:
        return notes, 0
    cap = max(1, int(round(limit * window)))
    buckets: dict[int, list[NoteEvent]] = {}
    for note in notes:
        buckets.setdefault(int(max(0.0, note.start) // window), []).append(note)
    kept: list[NoteEvent] = []
    for bucket in sorted(buckets):
        group = sorted(
            buckets[bucket],
            key=lambda item: (-_score(item), item.start, item.pitch, item.end),
        )
        kept.extend(group[:cap])
    return kept, len(notes) - len(kept)


def _cap_polyphony(notes: list[NoteEvent], cap: int) -> tuple[list[NoteEvent], int]:
    if cap <= 0 or len(notes) <= cap:
        return notes, 0
    ordered = sorted(notes, key=lambda item: (item.start, item.end, -_score(item)))
    active: dict[int, NoteEvent] = {}
    dropped: set[int] = set()
    end_heap: list[tuple[float, int]] = []
    score_heap: list[tuple[float, int]] = []
    counter = itertools.count()
    for note in ordered:
        while end_heap and end_heap[0][0] <= note.start:
            end, uid = heapq.heappop(end_heap)
            active.pop(uid, None)
        uid = next(counter)
        active[uid] = note
        heapq.heappush(end_heap, (note.end, uid))
        # Lower score first; on a tie prefer dropping the later note.
        heapq.heappush(score_heap, (_score(note), -uid, uid))
        while len(active) > cap:
            victim = None
            while score_heap:
                _, _, candidate = heapq.heappop(score_heap)
                if candidate in active:
                    victim = candidate
                    break
            if victim is None:
                break
            active.pop(victim, None)
            dropped.add(victim)
    kept = [note for index, note in enumerate(ordered) if index not in dropped]
    return kept, len(dropped)


def _reason_counts(removed: dict[str, int]) -> dict[str, int]:
    return {reason: int(removed.get(reason, 0)) for reason in REMOVAL_REASONS}


def fuse_notes(
    name: str,
    notes: Iterable[NoteEvent],
    *,
    evidence: EvidenceIndex | None = None,
    profile: FusionProfile | None = None,
    duration: float | None = None,
) -> tuple[list[NoteEvent], dict]:
    """Clean one instrument track and return ``(notes, stats)``.

    ``duration`` is the density-measurement span in seconds; when omitted the
    track's own first-to-last-note span is used.
    """
    profile = profile or profile_for(name)
    original = list(notes)
    stats = {
        "stem": name,
        "before": len(original),
        "after": len(original),
        "supported": 0,
        "removed": _reason_counts({}),
    }

    current, supported = _apply_support(original, evidence, profile)
    stats["supported"] = supported

    current, removed = _filter_confidence(current, profile)
    for reason, count in removed.items():
        stats["removed"][reason] += count

    current, same_pitch = _dedupe_same_pitch(current, profile.same_pitch_overlap)
    stats["removed"]["same_pitch_duplicate"] += same_pitch

    current, octaves = _dedupe_octaves(current, profile)
    stats["removed"]["octave_duplicate"] += octaves

    span = duration if duration is not None and duration > 0 else _track_span(current)
    current, density = _cap_density(current, profile, span)
    stats["removed"]["density"] += density

    current, polyphony = _cap_polyphony(current, profile.max_polyphony)
    stats["removed"]["polyphony"] += polyphony

    current.sort(key=lambda item: (item.start, item.pitch, item.end))
    stats["after"] = len(current)
    return current, stats


def enforce_quantized_limits(
    name: str,
    notes: Iterable[NoteEvent],
    profile: FusionProfile | None = None,
) -> tuple[list[NoteEvent], dict]:
    """Re-apply the polyphony cap after beat quantization.

    Two raw notes that did not overlap can snap onto the same grid cell and
    become simultaneous, so the pre-quantize cap alone is not sufficient.
    """
    profile = profile or profile_for(name)
    current = list(notes)
    stats = {
        "stem": name,
        "before": len(current),
        "after": len(current),
        "supported": 0,
        "removed": _reason_counts({}),
    }
    current, polyphony = _cap_polyphony(current, profile.max_polyphony)
    stats["removed"]["polyphony"] += polyphony
    current.sort(key=lambda item: (item.start, item.pitch, item.end))
    stats["after"] = len(current)
    return current, stats


def dedupe_quantized(notes: Iterable[NoteEvent]) -> tuple[list[NoteEvent], int]:
    """Remove identical grid notes, keeping the strongest one.

    Quantization can collapse two short fragments onto the same grid cell,
    producing exact duplicates that the pre-quantize passes cannot see.
    """
    best: dict[tuple[int, float, float], NoteEvent] = {}
    total = 0
    for note in notes:
        total += 1
        key = (int(note.pitch), round(float(note.start), 5), round(float(note.end), 5))
        current = best.get(key)
        if current is None or _score(note) > _score(current):
            best[key] = note
    unique = sorted(best.values(), key=lambda item: (item.start, item.pitch, item.end))
    return unique, total - len(unique)


def aggregate_stats(stats: Sequence[dict]) -> dict:
    """Fold per-track stats into the aggregate passed to ``metrics``."""
    aggregate = {
        "notes_before": 0,
        "notes_after": 0,
        "supported": 0,
        "removed": _reason_counts({}),
        "tracks": list(stats),
    }
    for item in stats:
        aggregate["notes_before"] += int(item.get("before", 0))
        aggregate["notes_after"] += int(item.get("after", 0))
        aggregate["supported"] += int(item.get("supported", 0))
        for reason, count in (item.get("removed") or {}).items():
            if reason in aggregate["removed"]:
                aggregate["removed"][reason] += int(count)
    return aggregate
