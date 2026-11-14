"""Instrument catalog and name/program resolution.

The catalog is the single source of truth for display names, MIDI programs,
ranges, polyphony, clefs and transposition.  The pipeline keeps the six core
stems for backward compatibility, but every track can carry an
``instrument_id`` resolved by this module.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

DEFAULT_CATALOG = Path(__file__).with_name("catalog.yaml")


def normalize_label(value: str | None) -> str:
    """Normalize a model/track label for alias lookup."""
    if not value:
        return ""
    label = str(value).strip().lower()
    if label.startswith("muscriptor_"):
        label = label[len("muscriptor_"):]
    label = re.sub(r"[_\-]+", " ", label)
    label = re.sub(r"\s+", " ", label).strip()
    return label


@dataclass(frozen=True)
class InstrumentProfile:
    id: str
    name_en: str
    name_zh: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    family: str = "other"
    gm_program: int = 48
    range_low: int = 24
    range_high: int = 108
    max_polyphony: int = 8
    monophonic: bool = False
    clef: str = "treble"
    transpose: int = 0
    notation: str = "staff"
    models: tuple[str, ...] = field(default_factory=tuple)
    source: str = "catalog"

    def display_name(self, language: str = "zh") -> str:
        if language.lower().startswith("zh") and self.name_zh:
            return self.name_zh
        return self.name_en or self.id

    def names(self) -> tuple[str, ...]:
        return (self.name_en, self.name_zh, *self.aliases)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["aliases"] = list(self.aliases)
        payload["models"] = list(self.models)
        payload["display_name"] = self.display_name()
        payload["range"] = [self.range_low, self.range_high]
        return payload


def _profile_from_dict(raw: dict) -> InstrumentProfile:
    instrument_range = raw.get("range") or [24, 108]
    if not isinstance(instrument_range, (list, tuple)) or len(instrument_range) != 2:
        instrument_range = [24, 108]
    return InstrumentProfile(
        id=str(raw["id"]),
        name_en=str(raw.get("name_en") or raw["id"]),
        name_zh=str(raw.get("name_zh") or raw.get("name_en") or raw["id"]),
        aliases=tuple(str(item) for item in (raw.get("aliases") or [])),
        family=str(raw.get("family") or "other"),
        gm_program=int(raw.get("gm_program", 48)),
        range_low=int(instrument_range[0]),
        range_high=int(instrument_range[1]),
        max_polyphony=int(raw.get("max_polyphony", 8)),
        monophonic=bool(raw.get("monophonic", False)),
        clef=str(raw.get("clef") or "treble"),
        transpose=int(raw.get("transpose", 0)),
        notation=str(raw.get("notation") or "staff"),
        models=tuple(str(item) for item in (raw.get("models") or [])),
        source=str(raw.get("source") or "catalog"),
    )


class InstrumentRegistry:
    def __init__(self, profiles: Iterable[InstrumentProfile]):
        self.profiles: dict[str, InstrumentProfile] = {}
        self._aliases: dict[str, str] = {}
        self._programs: dict[int, str] = {}
        for profile in profiles:
            if profile.id in self.profiles:
                raise ValueError(f"duplicate instrument id: {profile.id}")
            self.profiles[profile.id] = profile
            for name in profile.names():
                key = normalize_label(name)
                if key:
                    self._aliases.setdefault(key, profile.id)
            self._programs.setdefault(int(profile.gm_program), profile.id)

    def __len__(self) -> int:
        return len(self.profiles)

    def all(self) -> list[InstrumentProfile]:
        return sorted(self.profiles.values(), key=lambda item: (item.family, item.name_en))

    def get(self, instrument_id: str | None) -> InstrumentProfile | None:
        if not instrument_id:
            return None
        return self.profiles.get(str(instrument_id))

    def resolve(
        self,
        name: str | None,
        program: int | None = None,
        *,
        default: bool = False,
    ) -> InstrumentProfile | None:
        """Resolve a model label or MIDI program to a profile.

        Exact ids and aliases win; then the MIDI program; then a conservative
        substring match.  ``default=True`` returns a synthetic "Other" profile
        instead of None for unknown labels.
        """
        key = normalize_label(name)
        if key in self.profiles:
            return self.profiles[key]
        if key in self._aliases:
            return self.profiles[self._aliases[key]]
        if program is not None:
            matched = self._programs.get(int(program))
            if matched is not None and key in {"", "program", "other"}:
                return self.profiles[matched]
            if matched is not None and key.startswith("program"):
                return self.profiles[matched]
        if key.startswith("program"):
            parsed = program
            if parsed is None:
                match = re.search(r"(\d+)", key)
                parsed = int(match.group(1)) if match else None
            return self.synthetic(name, parsed)
        if key and not key.startswith("program"):
            for alias, instrument_id in self._aliases.items():
                if key in alias or alias in key:
                    return self.profiles[instrument_id]
        if default:
            return self.synthetic(name, program)
        return None

    def synthetic(self, name: str | None, program: int | None = None) -> InstrumentProfile:
        clean = normalize_label(name) or (
            f"program {program}" if program is not None else "other"
        )
        safe_id = re.sub(r"[^a-z0-9]+", "_", clean).strip("_") or "other"
        if not name or clean.startswith("program"):
            label = f"Other (program {program})" if program is not None else "Other"
        else:
            label = str(name)
        return InstrumentProfile(
            id=safe_id,
            name_en=label,
            name_zh=label,
            aliases=(),
            family="other",
            gm_program=int(program) if program is not None else 48,
            range_low=24,
            range_high=108,
            max_polyphony=8,
            monophonic=False,
            clef="treble",
            transpose=0,
            notation="staff",
            models=(),
            source="unknown",
        )


def load_registry(path: Path | None = None) -> InstrumentRegistry:
    path = Path(path) if path else DEFAULT_CATALOG
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_items = payload.get("instruments") or []
    profiles = [_profile_from_dict(item) for item in raw_items]
    return InstrumentRegistry(profiles)


REGISTRY = load_registry()
