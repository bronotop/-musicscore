"""Summarize transcription quality indicators for one project.

Examples:
    python scripts/quality_report.py --project runtime/data/projects/<id>
    python scripts/quality_report.py --project <dir> --json quality.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pretty_midi


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": round(ordered[0], 4),
        "median": round(ordered[len(ordered) // 2], 4),
        "mean": round(sum(ordered) / len(ordered), 4),
        "max": round(ordered[-1], 4),
    }


def _polyphony(notes: list[pretty_midi.Note], tolerance: float = 0.02) -> dict:
    """Approximate simultaneity: max notes sounding at once and overlap share."""
    if not notes:
        return {"max": 0, "overlap_ratio": 0.0}
    events: list[tuple[float, int]] = []
    for note in notes:
        events.append((note.start, 1))
        events.append((max(note.start + tolerance, note.end - tolerance), -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    active = 0
    maximum = 0
    overlapped = 0
    previous_time = None
    previous_active = 0
    for time, delta in events:
        if previous_time is not None and previous_active > 1:
            overlapped += int(round((time - previous_time) * 1000))
        active += delta
        maximum = max(maximum, active)
        previous_time = time
        previous_active = active
    span = max((note.end for note in notes), default=0.0)
    return {
        "max": maximum,
        "overlap_ratio": round(overlapped / (span * 1000), 4) if span > 0 else 0.0,
    }


def project_report(root: Path) -> dict:
    final_dir = root / "midi" / "final"
    confidence: dict[str, list[float]] = {}
    confidence_path = final_dir / "confidence.json"
    if confidence_path.exists():
        payload = json.loads(confidence_path.read_text(encoding="utf-8"))
        for track in payload.get("tracks", []):
            confidence[track.get("stem", "")] = [
                float(note.get("confidence", 1.0)) for note in track.get("notes", [])
            ]

    tracks = []
    for midi_path in sorted(final_dir.glob("*.mid")):
        if midi_path.name == "full.mid":
            continue
        midi = pretty_midi.PrettyMIDI(str(midi_path))
        notes = [note for instrument in midi.instruments for note in instrument.notes]
        durations = [note.end - note.start for note in notes]
        pitches = [note.pitch for note in notes]
        track = {
            "name": midi_path.stem,
            "notes": len(notes),
            "pitch_min": min(pitches) if pitches else None,
            "pitch_max": max(pitches) if pitches else None,
            "duration": _stats(durations),
            "polyphony": _polyphony(notes),
            "confidence": _stats(confidence.get(midi_path.stem, [])),
        }
        tracks.append(track)

    score = root / "score"
    xml = score / "full.musicxml"
    score_info = {
        "musicxml": xml.exists(),
        "lyrics": 0,
        "parts": 0,
        "pdf_pages": None,
        "svg_pages": len(list(score.glob("full.svg-p*.svg"))),
    }
    if xml.exists():
        text = xml.read_text(encoding="utf-8")
        score_info["lyrics"] = text.count("<lyric")
        score_info["parts"] = text.count("<score-part ")
    pdf = score / "full.pdf"
    if pdf.exists():
        try:
            from pypdf import PdfReader

            score_info["pdf_pages"] = len(PdfReader(str(pdf)).pages)
        except Exception:
            score_info["pdf_pages"] = "unreadable"

    lyrics_info = {"segments": 0, "words": 0, "language": None}
    lyrics_path = root / "midi" / "model" / "vocals.lyrics.json"
    if lyrics_path.exists():
        payload = json.loads(lyrics_path.read_text(encoding="utf-8"))
        lyrics_info["segments"] = len(payload.get("segments", []))
        lyrics_info["words"] = sum(
            len(segment.get("words") or []) for segment in payload.get("segments", [])
        )
        lyrics_info["language"] = payload.get("language")

    return {
        "project": root.name,
        "tracks": tracks,
        "total_notes": sum(track["notes"] for track in tracks),
        "score": score_info,
        "lyrics": lyrics_info,
    }


def _track_map(report: dict) -> dict[str, dict]:
    return {track["name"]: track for track in report.get("tracks", [])}


def _fmt(value) -> str:
    return "-" if value is None else f"{value:g}" if isinstance(value, (int, float)) else str(value)


def compare_reports(before: dict, after: dict) -> None:
    print(f"quality comparison: {before.get('project')} -> {after.get('project')}")
    print(f"{'track':28} {'notes':>13} {'max_poly':>13} {'conf_mean':>17}")
    old_tracks = _track_map(before)
    new_tracks = _track_map(after)
    for name in sorted(set(old_tracks) | set(new_tracks)):
        old = old_tracks.get(name, {})
        new = new_tracks.get(name, {})
        old_notes = old.get("notes", 0)
        new_notes = new.get("notes", 0)
        old_poly = (old.get("polyphony") or {}).get("max")
        new_poly = (new.get("polyphony") or {}).get("max")
        old_conf = (old.get("confidence") or {}).get("mean")
        new_conf = (new.get("confidence") or {}).get("mean")
        print(
            f"{name:28} {old_notes:>5}->{new_notes:<5} "
            f"{_fmt(old_poly):>5}->{_fmt(new_poly):<5} "
            f"{_fmt(old_conf):>6}->{_fmt(new_conf):<6}"
        )
    print(
        f"{'TOTAL':28} {before.get('total_notes', 0):>5}->{after.get('total_notes', 0):<5} "
        f"lyrics {before.get('lyrics', {}).get('words', 0)}->"
        f"{after.get('lyrics', {}).get('words', 0)} "
        f"pdf {before.get('score', {}).get('pdf_pages')}->"
        f"{after.get('score', {}).get('pdf_pages')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize transcription quality indicators")
    parser.add_argument("--project", required=True, help="project directory")
    parser.add_argument("--json", help="write the JSON report to this path")
    parser.add_argument("--compare", help="compare against a previous JSON report")
    args = parser.parse_args()

    root = Path(args.project)
    if not root.is_dir():
        parser.error(f"project directory not found: {root}")
    report = project_report(root)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        compare_reports(before, report)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
