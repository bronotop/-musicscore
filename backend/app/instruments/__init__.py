"""Instrument catalog."""

from app.instruments.registry import (
    REGISTRY,
    InstrumentProfile,
    InstrumentRegistry,
    load_registry,
    normalize_label,
)

__all__ = [
    "REGISTRY",
    "InstrumentProfile",
    "InstrumentRegistry",
    "load_registry",
    "normalize_label",
]
