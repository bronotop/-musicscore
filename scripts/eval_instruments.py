"""Evaluate solo-instrument transcription against the generated fixtures.

Example:
    python scripts/eval_instruments.py --fixtures runtime/data/fixtures \
        --project runtime/data/projects/<id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pretty_midi


def _load_manifest(root: Path, instrument: str | None) -> dict:
    path = root / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if instrument:
        if instrument not in payload:
            raise SystemExit(f"instrument not in manifest: {instrument}")
        return {instrument: payload[instrument]}
    return payload


def _midi_notes(root: Path, instrument: str | None) -> list[tuple[float, int]]:
    candidates = []
    if instrument:
        candidates.append(root / "midi" / "final" / f"{instrument}.mid")
    candidates.append(root / "midi" / "final" / "full.mid")
    for path in candidates:
        if path.exists():
            midi = pretty_midi.PrettyMIDI(str(path))
            return [
                (float(note.start), int(note.pitch))
                for midi_instrument in midi.instruments
                for note in midi_instrument.notes
            ]
    return []


def _match(
    reference: list[tuple[float, int]],
    estimate: list[tuple[float, int]],
    time_tolerance: float = 0.16,
) -> dict:
    used = set()
    matched = 0
    for ref_start, ref_pitch in reference:
        best = None
        for index, (est_start, est_pitch) in enumerate(estimate):
            if index in used or est_pitch != ref_pitch:
                continue
            delta = abs(est_start - ref_start)
            if delta <= time_tolerance and (best is None or delta < best[0]):
                best = (delta, index)
        if best is not None:
            used.add(best[1])
            matched += 1
    precision = matched / len(estimate) if estimate else 0.0
    recall = matched / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "reference": len(reference),
        "estimate": len(estimate),
        "matched": matched,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", required=True, help="fixture directory with manifest.json")
    parser.add_argument("--project", required=True, help="project directory")
    parser.add_argument("--instrument", help="evaluate one instrument (default: all)")
    args = parser.parse_args()

    fixtures = Path(args.fixtures)
    project = Path(args.project)
    manifest = _load_manifest(fixtures, args.instrument)
    report = {}
    for instrument, payload in manifest.items():
        reference = [
            (float(start), int(pitch))
            for start, _length, pitch in payload.get("notes", [])
        ]
        estimate = _midi_notes(project, instrument)
        report[instrument] = _match(reference, estimate)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
