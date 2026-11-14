"""Render the assembled MIDI into MusicXML, parts, PDF and SVG previews."""

from __future__ import annotations

from pathlib import Path

from app.pipeline.context import ProjectContext
from app.pipeline.stages.base import Stage, StageResult
from app.services.notation import (
    find_musescore,
    merge_pdfs,
    midi_to_musicxml,
    render_pdf,
    render_svg,
    split_musicxml_parts,
)


def _load_track_profiles(ctx: ProjectContext) -> dict[str, dict]:
    """Read ``midi/final/tracks.json`` into a track/instrument -> dict map."""
    try:
        payload = ctx.read_json(ctx.midi_final_dir / "tracks.json", {})
    except Exception:
        return {}
    profiles: dict[str, dict] = {}
    for track in payload.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        entry = dict(track)
        for key in (track.get("stem"), track.get("instrument_id")):
            if key:
                profiles[str(key)] = entry
    return profiles


class NotateStage(Stage):
    name = "notate"

    def input_files(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> list[Path]:
        files = [ctx.midi_final_dir / "full.mid"]
        tracks_path = ctx.midi_final_dir / "tracks.json"
        if tracks_path.exists():
            files.append(tracks_path)
        lyrics_path = ctx.midi_model_dir / "vocals.lyrics.json"
        if lyrics_path.exists():
            files.append(lyrics_path)
        return files

    def params(self, ctx: ProjectContext, upstream: dict[str, StageResult]) -> dict:
        lyrics_path = ctx.midi_model_dir / "vocals.lyrics.json"
        return {
            "quantize": True,
            "title": ctx.source.stem,
            "parts": True,
            "lyrics": lyrics_path.exists(),
            "track_profiles": _load_track_profiles(ctx),
        }

    def execute(self, ctx: ProjectContext, upstream: dict[str, StageResult]):
        full_midi = ctx.midi_final_dir / "full.mid"
        musicxml = ctx.score_dir / "full.musicxml"
        title = ctx.source.stem
        lyrics_path = ctx.midi_model_dir / "vocals.lyrics.json"
        lyrics = None
        if lyrics_path.exists():
            try:
                lyrics = ctx.read_json(lyrics_path, {})
            except Exception as exc:
                ctx.log(f"    lyrics skipped: {type(exc).__name__}: {exc}")

        track_profiles = _load_track_profiles(ctx)
        midi_to_musicxml(
            full_midi,
            musicxml,
            title=title,
            quantize=True,
            lyrics=lyrics,
            track_profiles=track_profiles or None,
        )
        if lyrics and lyrics.get("segments"):
            ctx.log(
                f"    lyrics: {sum(len(s.get('words') or []) for s in lyrics['segments'])} words"
            )
        ctx.log(f"    wrote {musicxml.name}")

        parts = split_musicxml_parts(musicxml, ctx.score_dir / "parts")
        ctx.log(f"    wrote {len(parts)} part(s)")

        pdf = None
        pdf_mode = "none"
        full_pdf = ctx.score_dir / "full.pdf"
        if find_musescore(ctx.musescore_path) is not None:
            try:
                pdf = render_pdf(musicxml, full_pdf, ctx.musescore_path)
                if pdf is not None:
                    pdf_mode = "full"
            except Exception as exc:
                ctx.log(
                    f"    full-score MusicXML PDF failed: {type(exc).__name__}: {exc}"
                )

            if pdf is None and full_midi.exists():
                try:
                    pdf = render_pdf(full_midi, full_pdf, ctx.musescore_path)
                    if pdf is not None:
                        pdf_mode = "midi"
                        ctx.log("    wrote full-score PDF from MIDI import")
                except Exception as exc:
                    ctx.log(
                        f"    MIDI-import PDF failed: {type(exc).__name__}: {exc}"
                    )

            if pdf is None:
                part_pdfs: list[Path] = []
                for part in parts:
                    part_pdf = part.with_suffix(".pdf")
                    try:
                        rendered = render_pdf(part, part_pdf, ctx.musescore_path)
                        if rendered is not None:
                            part_pdfs.append(rendered)
                    except Exception as part_exc:
                        ctx.log(f"    part PDF failed ({part.name}): {part_exc}")
                if part_pdfs:
                    try:
                        pdf = merge_pdfs(part_pdfs, full_pdf)
                        pdf_mode = "parts"
                        ctx.log(f"    wrote part-wise PDF ({len(part_pdfs)} parts)")
                    except Exception as merge_exc:
                        ctx.log(f"    part-wise PDF merge failed: {merge_exc}")

        svg_pages: list[Path] = []
        timemap_path = ctx.score_dir / "full.timemap.json"
        timemap_path.unlink(missing_ok=True)
        try:
            svg_pages = render_svg(musicxml, ctx.score_dir / "full.svg", timemap_path)
        except Exception as exc:
            if type(exc).__name__ != "ModuleNotFoundError":
                ctx.log(f"    svg render skipped: {type(exc).__name__}: {exc}")

        outputs: dict[str, Path] = {
            "musicxml": musicxml,
            "parts_dir": ctx.score_dir / "parts",
        }
        if pdf is not None:
            outputs["pdf"] = pdf
        if svg_pages:
            outputs["svg"] = svg_pages[0]
        if timemap_path.exists():
            outputs["timemap"] = timemap_path

        return outputs, {
            "musicxml_parts": len(parts),
            "pdf": pdf is not None,
            "pdf_mode": pdf_mode,
            "svg_pages": len(svg_pages),
            "timemap": timemap_path.exists(),
        }
