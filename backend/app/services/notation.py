"""MIDI -> MusicXML -> PDF/SVG rendering helpers."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from app.config import SETTINGS
from app.instruments import REGISTRY, InstrumentProfile, normalize_label
from app.services.piano_hands import choose_split_pitch


def _music21():
    from music21 import converter, metadata

    return converter, metadata


# General MIDI percussion -> (display-step, display-octave, notehead).
# Positions follow the common drum-kit staff layout around the percussion clef.
_DRUM_DISPLAY: dict[int, tuple[str, int, str]] = {
    35: ("F", 4, "normal"),    # acoustic bass drum
    36: ("F", 4, "normal"),    # bass drum 1
    37: ("C", 5, "x"),         # side stick
    38: ("C", 5, "normal"),    # acoustic snare
    39: ("C", 5, "x"),         # hand clap
    40: ("C", 5, "normal"),    # electric snare
    41: ("G", 4, "normal"),    # low floor tom
    42: ("G", 5, "x"),         # closed hi-hat
    43: ("A", 4, "normal"),    # high floor tom
    44: ("D", 4, "x"),         # pedal hi-hat
    45: ("A", 4, "normal"),    # low tom
    46: ("G", 5, "x"),         # open hi-hat
    47: ("B", 4, "normal"),    # low-mid tom
    48: ("D", 5, "normal"),    # hi-mid tom
    49: ("A", 5, "x"),         # crash cymbal 1
    50: ("E", 5, "normal"),    # high tom
    51: ("F", 5, "x"),         # ride cymbal 1
    52: ("A", 5, "x"),         # chinese cymbal
    53: ("F", 5, "diamond"),   # ride bell
    54: ("G", 5, "x"),         # tambourine
    55: ("A", 5, "x"),         # splash cymbal
    56: ("E", 5, "triangle"),  # cowbell
    57: ("A", 5, "x"),         # crash cymbal 2
    58: ("E", 5, "triangle"),  # vibraslap
    59: ("A", 5, "x"),         # ride cymbal 2
    60: ("C", 5, "normal"),    # hi bongo
    61: ("A", 4, "normal"),    # low bongo
    62: ("E", 5, "normal"),    # mute hi conga
    63: ("E", 5, "normal"),    # open hi conga
    64: ("C", 5, "normal"),    # low conga
    65: ("A", 4, "normal"),    # high timbale
    66: ("G", 4, "normal"),    # low timbale
    67: ("E", 5, "normal"),    # high agogo
    68: ("C", 5, "normal"),    # low agogo
    69: ("G", 5, "x"),         # cabasa
    70: ("G", 5, "x"),         # maracas
    71: ("C", 6, "normal"),    # short whistle
    72: ("C", 6, "normal"),    # long whistle
    73: ("G", 5, "normal"),    # short guiro
    74: ("G", 5, "normal"),    # long guiro
    75: ("E", 5, "normal"),    # claves
    76: ("C", 5, "normal"),    # hi wood block
    77: ("A", 4, "normal"),    # low wood block
    78: ("E", 5, "normal"),    # mute cuica
    79: ("E", 5, "normal"),    # open cuica
    80: ("E", 5, "triangle"),  # mute triangle
    81: ("E", 5, "triangle"),  # open triangle
}


def _parse_midi_with_pitched_drums(midi_path: Path):
    """Parse a MIDI file while keeping drum pitches.

    music21's MIDI importer turns channel-10 notes into unpitched percussion
    and discards the General MIDI pitch, so every drum collapses onto the same
    staff positions. Writing a temporary copy with ``is_drum=False`` preserves
    the GM pitches; :func:`_convert_drum_parts` maps them back to proper
    percussion notation afterwards.
    """
    converter, _ = _music21()
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(str(midi_path))
    drum_names = [inst.name for inst in midi.instruments if inst.is_drum]
    if not drum_names:
        return converter.parse(str(midi_path)), []

    handle = tempfile.NamedTemporaryFile(
        suffix=".mid", prefix="music2score-drums-", delete=False
    )
    temp_path = Path(handle.name)
    handle.close()
    try:
        for instrument in midi.instruments:
            if instrument.is_drum:
                instrument.is_drum = False
                if not instrument.name:
                    instrument.name = "drums"
        midi.write(str(temp_path))
        score = converter.parse(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)
    return score, [name.lower() for name in drum_names]


def _read_midi_program_map(midi_path: Path) -> tuple[dict[str, int], list[int]]:
    """Return ``(name -> GM program, programs in track order)``.

    music21's MIDI importer does not attach ``instrument.Instrument`` objects
    to imported parts, so the raw MIDI is the authoritative source for the
    program numbers used to resolve unknown instrument labels.
    """
    import pretty_midi

    by_name: dict[str, int] = {}
    by_index: list[int] = []
    try:
        midi = pretty_midi.PrettyMIDI(str(midi_path))
    except Exception:
        return by_name, by_index
    for instrument in midi.instruments:
        program = int(instrument.program)
        by_index.append(program)
        key = normalize_label(instrument.name)
        if key:
            by_name.setdefault(key, program)
    return by_name, by_index


def _drum_unpitched(pitch: int):
    from music21 import note

    step, octave, notehead = _DRUM_DISPLAY.get(pitch, ("C", 5, "normal"))
    unpitched = note.Unpitched()
    unpitched.displayStep = step
    unpitched.displayOctave = octave
    unpitched.notehead = notehead
    return unpitched


def _convert_drum_parts(score, drum_names: list[str]) -> None:
    """Convert pitched GM drum parts into readable percussion notation."""
    from music21 import clef, percussion, stream

    wanted = {name for name in drum_names if name}
    for part in score.parts:
        name = (part.partName or "").strip().lower()
        if not (name in wanted or "drum" in name or name == "kit"):
            continue
        for item in list(part.recurse().notes):
            try:
                pitches = [pitch.midi for pitch in item.pitches]
            except Exception:
                continue
            if not pitches:
                continue
            mapped = [_drum_unpitched(pitch) for pitch in pitches]
            try:
                velocity = getattr(getattr(item, "volume", None), "velocity", None)
                ghost = velocity is not None and int(velocity) <= 40
            except Exception:
                ghost = False
            if ghost:
                for unpitched in mapped:
                    unpitched.noteheadParenthesis = True
            replacement = (
                mapped[0] if len(mapped) == 1 else percussion.PercussionChord(mapped)
            )
            replacement.duration = copy.deepcopy(item.duration)
            try:
                replacement.volume = copy.deepcopy(item.volume)
            except Exception:
                pass
            site = item.activeSite
            if site is None:
                continue
            offset = item.offset
            site.remove(item)
            site.insert(offset, replacement)

        measures = part.getElementsByClass(stream.Measure)
        if measures:
            first = measures[0]
            for existing in list(first.getElementsByClass(clef.Clef)):
                first.remove(existing)
            first.insert(0, clef.PercussionClef())


def _clamp_note_durations(score, max_quarter_length: float = 4.0) -> None:
    """Clamp pathological held notes so makeNotation can split measures.

    MuScriptor occasionally emits a note sustained for the whole song. Without
    this guard music21 creates a single measure with a ``duplex-maxima``
    duration that MusicXML cannot serialize.
    """
    for item in score.recurse().notes:
        try:
            if item.duration.quarterLength > max_quarter_length:
                item.duration.quarterLength = max_quarter_length
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Lyric alignment helpers (used only by _apply_lyrics).

_VOWEL_CHARS = frozenset("aeiouyAEIOUY")
_ONSET_CLUSTERS = frozenset(
    (
        "bl", "br", "ch", "cl", "cr", "dr", "fl", "fr", "gl", "gr",
        "ph", "pl", "pr", "qu", "sc", "sh", "sk", "sl", "sm", "sn",
        "sp", "st", "sw", "th", "tr", "tw", "wh", "wr",
    )
)
_CODA_DIGRAPHS = frozenset(("ck", "ng"))
_CJK_RANGES = (
    (0x3040, 0x30FF),    # hiragana + katakana
    (0x31F0, 0x31FF),    # katakana phonetic extensions
    (0x3400, 0x4DBF),    # CJK extension A
    (0x4E00, 0x9FFF),    # CJK unified ideographs
    (0xF900, 0xFAFF),    # CJK compatibility ideographs
    (0xAC00, 0xD7AF),    # hangul syllables
    (0x20000, 0x3134F),  # CJK extensions B-G
)
_PYPHEN_CACHE: dict[str, object] = {}


def _is_cjk_char(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _CJK_RANGES)


def _is_cjk_text(text: str) -> bool:
    return any(_is_cjk_char(char) for char in text)


def _is_punctuation_or_space(char: str) -> bool:
    import unicodedata

    if char.isspace():
        return True
    return unicodedata.category(char)[0] in {"P", "Z"}


def _clean_lyric_token(text: str) -> str:
    """Trim surrounding whitespace/punctuation, preserving the original case."""
    cleaned = str(text).strip()
    while cleaned and _is_punctuation_or_space(cleaned[0]):
        cleaned = cleaned[1:].lstrip()
    while cleaned and _is_punctuation_or_space(cleaned[-1]):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _is_punctuation_only(text: str) -> bool:
    return bool(text) and all(_is_punctuation_or_space(char) for char in text)


def _split_cjk_units(text: str) -> list[str]:
    """Split CJK text into single characters, keeping Latin runs together."""
    units: list[str] = []
    buffer: list[str] = []
    for char in text:
        if _is_cjk_char(char):
            if buffer:
                units.append("".join(buffer))
                buffer = []
            units.append(char)
        elif char.isspace():
            if buffer:
                units.append("".join(buffer))
                buffer = []
        else:
            buffer.append(char)
    if buffer:
        units.append("".join(buffer))
    return [unit for unit in units if unit and not _is_punctuation_only(unit)]


def _pyphen_syllables(
    word: str, language: str
) -> tuple[list[str] | None, bool]:
    """Return (syllables, pyphen_available) without requiring pyphen."""
    try:
        import pyphen
    except Exception:
        return None, False

    lang = (language or "en").replace("-", "_")
    candidates = []
    if "_" not in lang:
        # Region-qualified English dictionaries give better syllables than the
        # bare "en" fallback (e.g. en_US: hel-lo, for-ev-er).
        candidates.extend([f"{lang}_US", f"{lang}_GB"])
    candidates.append(lang)
    available = False
    for candidate in candidates:
        dictionary = _PYPHEN_CACHE.get(candidate)
        if dictionary is None:
            try:
                dictionary = pyphen.Pyphen(lang=candidate)
            except Exception:
                continue
            _PYPHEN_CACHE[candidate] = dictionary
        available = True
        try:
            parts = [part for part in dictionary.inserted(word).split("-") if part]
        except Exception:
            continue
        if len(parts) >= 2 and "".join(parts).lower() == word.lower():
            return parts, True
    return None, available


def _vowel_syllable_split(word: str) -> list[str]:
    """Simple vowel-group syllable split for Latin-script words."""
    groups: list[tuple[int, int]] = []
    index = 0
    length = len(word)
    while index < length:
        if word[index] in _VOWEL_CHARS:
            end = index + 1
            while end < length and word[end] in _VOWEL_CHARS:
                end += 1
            groups.append((index, end))
            index = end
        else:
            index += 1
    if len(groups) < 2:
        return [word]

    boundaries: list[int] = []
    for (_, vowel_end), (next_start, _) in zip(groups, groups[1:]):
        cluster = word[vowel_end:next_start]
        lowered = cluster.lower()
        if not cluster:
            boundaries.append(next_start)
        elif len(cluster) == 1:
            boundaries.append(vowel_end)
        elif lowered in _CODA_DIGRAPHS:
            boundaries.append(next_start)
        elif lowered in _ONSET_CLUSTERS:
            boundaries.append(vowel_end)
        else:
            boundaries.append(vowel_end + 1)

    parts: list[str] = []
    previous = 0
    for boundary in boundaries:
        if previous < boundary < length:
            parts.append(word[previous:boundary])
            previous = boundary
    parts.append(word[previous:])
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return [word]
    if any(part.startswith(("'", "’")) for part in parts):
        return [word]
    return parts


def _split_english_syllables(word: str, language: str) -> list[str]:
    """Best-effort English syllable split without network dependencies.

    pyphen is authoritative when its dictionary is available; the vowel-group
    heuristic is only used when pyphen has no dictionary for the language.
    """
    if len(word) < 4:
        return [word]
    if not all(char.isalpha() or char in "'’" for char in word):
        return [word]
    parts, pyphen_available = _pyphen_syllables(word, language)
    if parts:
        return parts
    if pyphen_available:
        # The dictionary could not split the word; keep it whole (melisma).
        return [word]
    return _vowel_syllable_split(word)


def _collect_lyric_words(payload: dict) -> list[tuple[float, float, str]]:
    words: list[tuple[float, float, str]] = []
    for segment in payload.get("segments", []) or []:
        try:
            segment_start = float(segment.get("start", 0.0))
            segment_end = float(segment.get("end", segment_start))
        except (TypeError, ValueError):
            continue
        segment_words = segment.get("words") or []
        if not segment_words:
            tokens = str(segment.get("text", "")).split()
            if tokens:
                span = max(0.01, (segment_end - segment_start) / len(tokens))
                for index, token in enumerate(tokens):
                    words.append(
                        (
                            segment_start + index * span,
                            segment_start + (index + 1) * span,
                            token,
                        )
                    )
            continue
        for word in segment_words:
            if not isinstance(word, dict):
                continue
            raw = str(word.get("word", "")).strip()
            if not raw:
                continue
            try:
                start = float(word.get("start", segment_start))
                end = float(word.get("end", segment_end))
            except (TypeError, ValueError):
                start, end = segment_start, segment_end
            if end <= start:
                end = start + 0.01
            words.append((start, end, raw))
    words.sort(key=lambda item: (item[0], item[1]))
    return words


def _collect_lyric_slots(vocal) -> list[dict]:
    """Collect vocal notes as time-ordered lyric slots.

    The slots are sorted by absolute onset so multiple voices/measures cannot
    reorder words. Notes that already carry a lyric are pre-marked as owned.
    """
    slots: list[dict] = []
    try:
        seconds_map = vocal.flatten().secondsMap
    except Exception:
        return slots
    for order, entry in enumerate(seconds_map):
        element = entry.get("element")
        if element is None:
            continue
        if not (
            getattr(element, "isNote", False)
            or getattr(element, "isChord", False)
        ):
            continue
        try:
            start = float(entry.get("offsetSeconds", 0.0))
            duration = float(entry.get("durationSeconds", 0.0))
        except (TypeError, ValueError):
            continue
        if duration <= 0.0:
            continue
        existing = ""
        for lyric in getattr(element, "lyrics", None) or []:
            text = getattr(lyric, "text", "") or ""
            if text.strip():
                existing = text
                break
        slots.append(
            {
                "start": start,
                "end": start + duration,
                "element": element,
                "order": order,
                "owner": -1 if existing else None,
            }
        )
    slots.sort(key=lambda slot: (slot["start"], slot["end"], slot["order"]))
    return slots


def _set_note_lyric(element, text: str, syllabic: str = "single") -> bool:
    """Write one lyric, including its MusicXML syllabic value when possible."""
    if not text:
        return False
    try:
        from music21 import note as m21note

        lyric = m21note.Lyric(text=text)
        if syllabic in {"single", "begin", "middle", "end"}:
            lyric.syllabic = syllabic
        element.lyric = lyric
        return True
    except Exception:
        return False


def _apply_lyrics(score, payload: dict) -> int:
    """Attach transcribed words to vocal notes in absolute time order.

    ``payload`` is the JSON written by the faster-whisper adapter:
    ``{"language": ..., "segments": [{"start", "end", "text", "words": [...]}]}``.

    Strategy per word:
    * notes are considered in time order (never voice/measure order);
    * free notes are preferred, then the nearest free note within 0.4 s;
    * English words spanning several notes are split into syllables with
      begin/middle/end when possible, otherwise only the leading note carries
      the word (melisma: later notes stay empty);
    * CJK words are distributed one character per note; surplus characters are
      merged into the last note of the same word;
    * pure punctuation/whitespace tokens are ignored.

    Returns the number of notes that received a lyric.
    """
    if not payload:
        return 0

    vocal = None
    for part in score.parts:
        name = (part.partName or "").lower()
        if "vocal" in name or "voice" in name or "人声" in name:
            vocal = part
            break
    if vocal is None:
        return 0

    slots = _collect_lyric_slots(vocal)
    if not slots:
        return 0

    language = str(payload.get("language") or "en").lower()
    words = _collect_lyric_words(payload)

    def choose_slots(word_start: float, word_end: float) -> list[dict]:
        covered: list[dict] = []
        for slot in slots:
            overlap = min(word_end, slot["end"]) - max(word_start, slot["start"])
            if overlap <= 0.0:
                continue
            span = min(word_end - word_start, slot["end"] - slot["start"])
            if overlap < 0.03 or overlap < 0.3 * max(span, 1e-6):
                continue
            covered.append(slot)
        covered.sort(key=lambda slot: (slot["start"], slot["order"]))
        free = [slot for slot in covered if slot["owner"] is None]
        if free:
            return free

        nearest = None
        nearest_key = None
        for slot in slots:
            if slot["owner"] is not None:
                continue
            if slot["end"] < word_start:
                distance = word_start - slot["end"]
            elif slot["start"] > word_end:
                distance = slot["start"] - word_end
            else:
                distance = 0.0
            if distance > 0.4:
                continue
            key = (
                distance,
                abs(slot["start"] - word_start),
                slot["start"],
                slot["order"],
            )
            if nearest_key is None or key < nearest_key:
                nearest_key, nearest = key, slot
        return [nearest] if nearest is not None else []

    applied = 0
    for word_index, (start, end, raw_text) in enumerate(words):
        text = _clean_lyric_token(raw_text)
        if not text:
            continue
        targets = choose_slots(start, end)
        if not targets:
            continue

        if _is_cjk_text(text):
            units = _split_cjk_units(text)
            if not units:
                continue
            if len(units) <= len(targets):
                for index, unit in enumerate(units):
                    if _set_note_lyric(targets[index]["element"], unit):
                        applied += 1
                    targets[index]["owner"] = word_index
            else:
                last_index = len(targets) - 1
                for index in range(last_index):
                    if _set_note_lyric(targets[index]["element"], units[index]):
                        applied += 1
                    targets[index]["owner"] = word_index
                merged = "".join(units[last_index:])
                if _set_note_lyric(targets[last_index]["element"], merged):
                    applied += 1
                targets[last_index]["owner"] = word_index
            used = min(len(units), len(targets))
            for slot in targets[used:]:
                slot["owner"] = word_index
            continue

        syllables = (
            _split_english_syllables(text, language) if len(targets) > 1 else [text]
        )
        if 2 <= len(syllables) <= len(targets):
            for index, syllable in enumerate(syllables):
                if index == 0:
                    syllabic = "begin"
                elif index == len(syllables) - 1:
                    syllabic = "end"
                else:
                    syllabic = "middle"
                if _set_note_lyric(targets[index]["element"], syllable, syllabic):
                    applied += 1
                targets[index]["owner"] = word_index
            used = len(syllables)
        else:
            if _set_note_lyric(targets[0]["element"], text):
                applied += 1
            targets[0]["owner"] = word_index
            used = 1
        # Remaining notes hold the same syllable: mark them as used so a later
        # word cannot be squeezed in, but leave their lyric empty.
        for slot in targets[used:]:
            slot["owner"] = word_index

    return applied


def midi_to_musicxml(
    midi_path: Path,
    out_path: Path,
    title: str | None = None,
    quantize: bool = True,
    lyrics: dict | None = None,
    track_profiles: dict | None = None,
) -> Path:
    """Convert a MIDI file into a MusicXML score.

    music21's MIDI importer is lossy for performance timing; we quantize and
    run makeNotation so the result is at least readable. The caller can render
    PDF/SVG from the returned MusicXML.

    ``track_profiles`` optionally maps a MIDI track/instrument name (and/or an
    instrument id from ``tracks.json``) to catalog metadata. When omitted the
    instrument registry is used to resolve names/programs by itself.
    """
    converter, metadata = _music21()
    midi_path = Path(midi_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    score, drum_parts = _parse_midi_with_pitched_drums(midi_path)

    programs_by_name, programs_by_index = _read_midi_program_map(midi_path)
    profile_lookup = _build_profile_lookup(track_profiles)
    profiles = _profiles_for_score(
        score, profile_lookup, programs_by_name, programs_by_index
    )
    try:
        _drop_notation_none_parts(score, profiles)
    except Exception:
        pass

    if quantize:
        try:
            score.quantize(
                quarterLengthDivisors=(4, 3),
                processOffsets=True,
                processDurations=True,
                inPlace=True,
            )
        except Exception:
            # Leave timing as-is rather than losing the whole score.
            pass

    try:
        _clamp_note_durations(score)
    except Exception:
        pass

    try:
        score.makeNotation(inPlace=True)
    except Exception:
        pass

    try:
        percussion_names = [
            (part.partName or "").lower()
            for part in score.parts
            if profiles.get(id(part)) is not None
            and profiles[id(part)].notation == "percussion"
        ]
        _convert_drum_parts(score, [*drum_parts, *percussion_names])
    except Exception:
        pass

    if lyrics:
        try:
            _apply_lyrics(score, lyrics)
        except Exception:
            pass

    if title:
        if score.metadata is None:
            score.insert(0, metadata.Metadata())
        score.metadata.title = title
    if score.metadata is not None and (score.metadata.composer or "").strip().lower() == "music21":
        score.metadata.composer = ""

    try:
        _polish_score(score, profiles, programs_by_name, programs_by_index)
    except Exception:
        pass

    try:
        _expand_grand_staff_parts(score, profiles)
    except Exception:
        pass

    try:
        _apply_part_transposition(score, profiles)
    except Exception:
        pass

    score.write("musicxml", fp=str(out_path))

    # MuseScore 4.7.6 can crash on music21's first-pass serialization for
    # large multi-part scores. Parsing and writing it again normalizes the
    # stream/voice/backup structure; this is a no-op for small scores.
    try:
        normalize_musicxml(out_path)
    except Exception:
        pass
    _strip_music21_credit(out_path)

    return out_path


def _strip_music21_credit(path: Path) -> None:
    """Remove music21's default composer credit from generated scores."""
    try:
        text = path.read_text(encoding="utf-8")
        cleaned = text.replace('<creator type="composer">Music21</creator>', "")
        cleaned = cleaned.replace('<creator type="lyricist">Music21</creator>', "")
        if cleaned != text:
            path.write_text(cleaned, encoding="utf-8")
    except Exception:
        pass


def normalize_musicxml(path: Path) -> Path:
    """Re-serialize MusicXML to make it robust for MuseScore import."""
    converter, _ = _music21()
    path = Path(path)
    temp = path.with_name(f"{path.stem}.normalized.musicxml")
    try:
        score = converter.parse(str(path))
        score.write("musicxml", fp=str(temp))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def _program_from_label(label: str | None) -> int | None:
    match = re.search(r"program[ _-]?(\d+)", str(label or ""), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _coerce_profile(value, label: str) -> InstrumentProfile:
    """Normalize a ``track_profiles`` value into an instrument profile.

    Values may be full profile dicts (as written to ``tracks.json``), minimal
    dicts such as ``{"clef": "bass"}``, an ``InstrumentProfile`` or a label.
    Explicit dict fields override the catalog, which lets the pipeline carry
    per-track decisions while keeping the catalog authoritative by default.
    """
    if isinstance(value, InstrumentProfile):
        return value

    if isinstance(value, dict):
        instrument_id = value.get("instrument_id") or value.get("id")
        raw_program = value.get("program", value.get("gm_program"))
        program = None
        if raw_program is not None:
            try:
                program = int(raw_program)
            except (TypeError, ValueError):
                program = None
        profile = REGISTRY.get(str(instrument_id)) if instrument_id else None
        if profile is None:
            profile = REGISTRY.resolve(
                str(instrument_id or label), program, default=True
            )
        overlay: dict = {}
        for key in ("name_en", "name_zh", "family", "clef", "notation"):
            raw = value.get(key)
            if raw:
                overlay[key] = str(raw)
        if value.get("transpose") is not None:
            try:
                overlay["transpose"] = int(value["transpose"])
            except (TypeError, ValueError):
                pass
        if value.get("monophonic") is not None:
            overlay["monophonic"] = bool(value["monophonic"])
        if program is not None:
            overlay["gm_program"] = program
        return replace(profile, **overlay) if overlay else profile

    if value is not None:
        return REGISTRY.resolve(str(value), default=True)
    return REGISTRY.resolve(label, default=True)


def _build_profile_lookup(track_profiles: dict | None) -> dict[str, InstrumentProfile]:
    lookup: dict[str, InstrumentProfile] = {}
    for key, value in (track_profiles or {}).items():
        label = str(key)
        try:
            profile = _coerce_profile(value, label)
        except Exception:
            continue
        for candidate in (
            label,
            profile.id,
            profile.name_en,
            profile.name_zh,
            *profile.aliases,
        ):
            normalized = normalize_label(candidate)
            if normalized:
                lookup.setdefault(normalized, profile)
    return lookup


def _profile_for_label(
    label: str | None,
    program: int | None = None,
    lookup: dict[str, InstrumentProfile] | None = None,
) -> InstrumentProfile:
    """Resolve one part label to a registry profile (never returns None)."""
    raw = str(label or "").strip()
    key = normalize_label(raw)

    if lookup and key:
        profile = lookup.get(key)
        if profile is not None:
            return profile

    if key:
        direct = REGISTRY.get(key)
        if direct is not None:
            return direct

    resolved = REGISTRY.resolve(raw, program, default=False)
    if resolved is not None:
        return resolved

    # Legacy labels the catalog does not cover yet (e.g. "choir"). Keeping
    # them readable preserves the pre-registry behavior for projects without
    # tracks.json metadata.
    friendly = _FRIENDLY_PART_NAMES.get(raw.lower())
    if friendly:
        base = REGISTRY.resolve(friendly, program, default=True)
        return replace(
            base, name_en=friendly, name_zh=friendly, source="legacy"
        )

    return REGISTRY.resolve(raw, program, default=True)


def _profiles_for_score(
    score,
    lookup: dict[str, InstrumentProfile],
    programs_by_name: dict[str, int] | None = None,
    programs_by_index: list[int] | None = None,
) -> dict[int, InstrumentProfile]:
    profiles: dict[int, InstrumentProfile] = {}
    programs_by_name = programs_by_name or {}
    programs_by_index = programs_by_index or []
    for index, part in enumerate(score.parts):
        label = part.partName or ""
        program = programs_by_name.get(normalize_label(label))
        if program is None and index < len(programs_by_index):
            program = programs_by_index[index]
        profiles[id(part)] = _profile_for_label(label, program, lookup)
    return profiles


def _profile_display_name(
    profile: InstrumentProfile | None, program: int | None = None
) -> str:
    """English MusicXML part name for *profile*."""
    if profile is None:
        return "Other"
    if profile.source == "legacy":
        return profile.name_en or profile.id or "Other"
    if profile.source == "unknown":
        number = program
        if number is None:
            number = _program_from_label(profile.id)
        if number is None:
            number = _program_from_label(profile.name_en)
        if number is not None:
            return f"Other (program {int(number)})"
        return "Other"
    return profile.name_en or profile.id or "Other"


def _drop_notation_none_parts(score, profiles: dict[int, InstrumentProfile]) -> int:
    """Remove tracks whose profile has ``notation: none`` (FX, etc.)."""
    removed = 0
    for part in list(score.parts):
        profile = profiles.get(id(part))
        if profile is not None and (profile.notation or "staff").lower() == "none":
            score.remove(part)
            removed += 1
    return removed


def _clef_for_name(name: str | None):
    """Build a music21 clef for a catalog clef token."""
    from music21 import clef

    key = (name or "treble").strip().lower().replace("_", "")
    if key in {"grand", "none"}:
        return None
    if key == "bass":
        return clef.BassClef()
    if key in {"alto", "c3"}:
        return clef.AltoClef()
    if key in {"tenor", "c4"}:
        return clef.TenorClef()
    if key in {"percussion", "unpitched"}:
        return clef.PercussionClef()
    if key in {"treble8vb", "treble8", "treble-8"}:
        return clef.Treble8vbClef()
    if key in {"bass8vb", "bass8", "bass-8"}:
        return clef.Bass8vbClef()
    return clef.TrebleClef()


# Legacy label -> readable English name.  The instrument catalog is the
# primary source for names/clefs/transposition; this table only covers old
# labels the catalog does not include yet so projects without tracks.json keep
# their previous part names.
_FRIENDLY_PART_NAMES = {
    "vocals": "Voice",
    "drums": "Drum Kit",
    "guitar": "Acoustic Guitar",
    "piano": "Piano",
    "bass": "Bass",
    "other": "Other",
    "muscriptor_trumpet": "Trumpet",
    "muscriptor_french horn": "French Horn",
    "muscriptor_tenor sax": "Tenor Sax",
    "muscriptor_baritone sax": "Baritone Sax",
    "muscriptor_bassoon": "Bassoon",
    "muscriptor_synth pad": "Synth Pad",
    "muscriptor_flute": "Flute",
    "muscriptor_flutes": "Flute",
    "muscriptor_clarinet": "Clarinet",
    "muscriptor_oboe": "Oboe",
    "muscriptor_trombone": "Trombone",
    "muscriptor_tuba": "Tuba",
    "muscriptor_brass section": "Brass",
    "muscriptor_strings": "Strings",
    "muscriptor_violin": "Violin",
    "muscriptor_viola": "Viola",
    "muscriptor_cello": "Cello",
    "muscriptor_contrabass": "Contrabass",
    "muscriptor_organ": "Organ",
    "muscriptor_choir": "Choir",
    "muscriptor_synth lead": "Synth Lead",
    "muscriptor_acoustic guitar": "Acoustic Guitar",
    "muscriptor_clean electric guitar": "Clean Guitar",
    "muscriptor_distorted electric guitar": "Distorted Guitar",
}


def _polish_score(
    score,
    profiles: dict[int, InstrumentProfile] | None = None,
    programs_by_name: dict[str, int] | None = None,
    programs_by_index: list[int] | None = None,
) -> None:
    """Apply catalog part names and clefs to every part."""
    from music21 import stream

    profiles = profiles if profiles is not None else {}
    programs_by_name = programs_by_name or {}
    programs_by_index = programs_by_index or []

    for index, part in enumerate(score.parts):
        profile = profiles.get(id(part))
        program = programs_by_name.get(normalize_label(part.partName or ""))
        if program is None and index < len(programs_by_index):
            program = programs_by_index[index]
        if profile is None:
            profile = _profile_for_label(part.partName or "", program)
            profiles[id(part)] = profile

        display = _profile_display_name(profile, program)
        if display:
            part.partName = display

        clef_name = (profile.clef or "treble").lower()
        if (profile.notation or "staff").lower() == "percussion":
            # Percussion notation always uses the unpitched clef, even if a
            # hand-written profile pairs it with another clef token.
            clef_name = "percussion"
        if clef_name == "grand":
            # A grand-staff part is split into two PartStaff objects later.
            continue

        try:
            new_clef = _clef_for_name(clef_name)
            if new_clef is None:
                continue
            measures = part.getElementsByClass(stream.Measure)
            if not measures:
                continue
            first = measures[0]
            for existing in list(first.getElementsByClass("Clef")):
                first.remove(existing)
            first.insert(0, new_clef)
            if (profile.notation or "staff").lower() == "percussion":
                part.partAbbreviation = display or profile.name_en or "Percussion"
        except Exception:
            continue


PIANO_SPLIT_PITCH = 60  # middle C: right hand above, left hand below


def _split_piano_part(
    part, keep_high: bool, split_pitch: int = PIANO_SPLIT_PITCH
):
    """Clone one hand of a piano part while keeping the measure structure."""
    from music21 import chord, clef, stream

    split = stream.PartStaff()
    split.partName = part.partName or "Piano"
    for measure in part.getElementsByClass(stream.Measure):
        clone = copy.deepcopy(measure)
        for item in list(clone.recurse().notes):
            try:
                pitches = list(item.pitches)
            except Exception:
                continue
            keep = [
                pitch
                for pitch in pitches
                if (pitch.midi >= split_pitch) == keep_high
            ]
            if not keep:
                if item.activeSite is not None:
                    item.activeSite.remove(item)
            elif len(keep) != len(pitches) and item.isChord:
                replacement = chord.Chord(keep)
                replacement.duration = copy.deepcopy(item.duration)
                try:
                    replacement.volume = copy.deepcopy(item.volume)
                except Exception:
                    pass
                site, offset = item.activeSite, item.offset
                if site is not None:
                    site.remove(item)
                    site.insert(offset, replacement)
        for clef_element in list(clone.recurse().getElementsByClass(clef.Clef)):
            if clef_element.activeSite is not None:
                clef_element.activeSite.remove(clef_element)
        try:
            clone.makeRests(fillGaps=True, inPlace=True)
        except Exception:
            pass
        split.insert(measure.offset, clone)

    measures = split.getElementsByClass(stream.Measure)
    if measures:
        measures[0].insert(
            0, clef.TrebleClef() if keep_high else clef.BassClef()
        )
    return split


def _expand_grand_staff_parts(
    score, profiles: dict[int, InstrumentProfile] | None = None
) -> set[int]:
    """Replace every ``clef: grand`` part with a two-staff grand-staff part.

    music21's ``PartStaff`` objects are serialized as one MusicXML part with
    ``<staves>2</staves>``, so MuseScore draws a braced grand staff.  The
    piano two-staff split is generalized to any catalog profile whose clef is
    ``grand`` (piano, harp, organ, yangqin, strings, ...).
    """
    from music21 import layout, stream

    profiles = profiles if profiles is not None else {}
    expanded: set[int] = set()
    for part in list(score.parts):
        profile = profiles.get(id(part))
        if profile is None or (profile.clef or "").lower() != "grand":
            continue
        name = (part.partName or "").strip().lower()
        if "rh" in name or "lh" in name:
            continue
        if not list(part.recurse().notes):
            continue
        if not list(part.getElementsByClass(stream.Measure)):
            continue
        pitches: list[int] = []
        for item in part.recurse().notes:
            try:
                pitches.extend(int(pitch.midi) for pitch in item.pitches)
            except Exception:
                continue
        split_pitch = choose_split_pitch(pitches)
        right = _split_piano_part(part, keep_high=True, split_pitch=split_pitch)
        left = _split_piano_part(part, keep_high=False, split_pitch=split_pitch)
        if not list(right.recurse().notes) and not list(left.recurse().notes):
            continue
        offset = part.offset
        score.remove(part)
        score.insert(offset, right)
        score.insert(offset, left)
        score.insert(
            0,
            layout.StaffGroup(
                [right, left],
                symbol="brace",
                name=part.partName or profile.name_en or "Grand Staff",
                barTogether=True,
            ),
        )
        profiles[id(right)] = profile
        profiles[id(left)] = profile
        expanded.add(id(part))
    return expanded


def _apply_part_transposition(score, profiles: dict[int, InstrumentProfile]) -> int:
    """Expose concert-pitch MIDI as written pitch for transposing instruments.

    MIDI stores sounding pitch.  MusicXML needs written pitch plus a
    ``<transpose>`` element.  We therefore mark the score as sounding and give
    each transposing part an ``instrument.Instrument`` whose ``transposition``
    is ``-profile.transpose``; music21's MusicXML exporter then performs the
    sounding -> written conversion exactly once (no manual note transposition,
    hence no double transposition).  Parts that music21 already holds at
    written pitch are normalized to sounding first.
    """
    from music21 import instrument, interval

    transposed = 0
    for part in score.parts:
        profile = profiles.get(id(part))
        if profile is None:
            continue
        try:
            semitones = int(profile.transpose or 0)
        except (TypeError, ValueError):
            semitones = 0
        if semitones == 0:
            continue

        existing = list(part.getElementsByClass(instrument.Instrument))
        try:
            if part.atSoundingPitch is False and existing:
                part.toSoundingPitch(inPlace=True)
        except Exception:
            pass

        written_instrument = instrument.Instrument()
        written_instrument.instrumentName = (
            part.partName or profile.name_en or profile.id
        )
        written_instrument.partName = written_instrument.instrumentName
        written_instrument.midiProgram = int(profile.gm_program)
        written_instrument.transposition = interval.Interval(-semitones)

        for old in list(part.getElementsByClass(instrument.Instrument)):
            part.remove(old)
        part.insert(0, written_instrument)
        part.atSoundingPitch = True
        transposed += 1

    if transposed:
        score.atSoundingPitch = True
    return transposed


def split_musicxml_parts(xml_path: Path, out_dir: Path) -> list[Path]:
    """Write one MusicXML file per part (instrument).

    This splits the already-rendered MusicXML at the XML level. Re-importing
    and re-serializing each part with music21 re-runs ``makeNotation()`` and
    can crash on scores whose voice ids change between measures (KeyError in
    ``makeTies``). Copying ``<score-part>`` / ``<part>`` pairs preserves the
    exact notation, including grand staves.
    """
    from xml.etree import ElementTree as ET

    xml_path = Path(xml_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.iterdir():
        if stale.is_file() and stale.suffix.lower() in (".musicxml", ".pdf"):
            stale.unlink()

    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
        ET.register_namespace("", namespace)

    def q(tag: str) -> str:
        return f"{{{namespace}}}{tag}" if namespace else tag

    part_list = root.find(q("part-list"))
    if part_list is None:
        return []
    score_parts = part_list.findall(q("score-part"))
    parts_by_id = {part.get("id"): part for part in root.findall(q("part"))}

    paths: list[Path] = []
    written = 0
    for index, score_part in enumerate(score_parts, start=1):
        part = parts_by_id.get(score_part.get("id"))
        if part is None:
            continue

        single = ET.Element(root.tag, dict(root.attrib))
        for child in root:
            if child is part_list or child.tag == q("part"):
                continue
            single.append(copy.deepcopy(child))
        new_list = ET.SubElement(single, q("part-list"))
        new_list.append(copy.deepcopy(score_part))
        single.append(copy.deepcopy(part))

        name = score_part.findtext(q("part-name")) or f"part{index}"
        safe = "".join(
            ch if ch.isalnum() or ch in "-_ " else "_" for ch in name
        ).strip().replace(" ", "_")
        written += 1
        target = out_dir / f"{written:02d}_{safe or 'part'}.musicxml"
        ET.ElementTree(single).write(
            str(target), encoding="utf-8", xml_declaration=True
        )
        paths.append(target)
    return paths


def find_musescore(explicit: str | None = None) -> Path | None:
    candidates = [
        explicit,
        os.environ.get("MUSESCORE_PATH"),
        str(SETTINGS.home / "vendor" / "MuseScore4" / "MuseScore 4" / "bin" / "MuseScore4.exe"),
        str(SETTINGS.home / "vendor" / "MuseScore4" / "bin" / "MuseScore4.exe"),
        r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
        r"C:\Program Files\MuseScore 4\bin\mscore.exe",
        r"C:\Program Files\MuseScore 3\bin\MuseScore3.exe",
        r"C:\Program Files\MuseScore 3\bin\mscore.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    for name in ("MuseScore4", "musescore", "mscore", "MuseScore3"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def render_pdf(xml_path: Path, pdf_path: Path, musescore_path: str | None = None) -> Path | None:
    """Render MusicXML (or MIDI) to PDF with MuseScore CLI, if available."""
    exe = find_musescore(musescore_path)
    if exe is None:
        return None
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(exe), "-f", "-o", str(pdf_path), str(xml_path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0 or not pdf_path.exists():
        detail = (result.stderr or result.stdout or "").strip()[-600:]
        raise RuntimeError(
            f"MuseScore export failed (exit {result.returncode}): {detail}"
        )
    return pdf_path


def render_svg(
    xml_path: Path,
    svg_prefix: Path,
    timemap_path: Path | None = None,
) -> list[Path]:
    """Render MusicXML pages to SVG with Verovio (optional dependency).

    When ``timemap_path`` is given, write the Verovio timemap (note id ->
    millisecond timestamp) used for score-follow playback. A fixed xml id seed
    keeps SVG ids stable across renders.
    """
    import verovio

    toolkit = verovio.toolkit()
    toolkit.setOptions({"xmlIdSeed": 20261031})
    # Verovio's C++ loadFile cannot open non-ASCII paths on Windows, so load
    # the decoded XML instead (project ids may contain Chinese characters).
    if not toolkit.loadData(Path(xml_path).read_text(encoding="utf-8")):
        raise RuntimeError(f"Verovio could not parse {xml_path}")
    toolkit.setOptions(
        {"pageWidth": 2100, "adjustPageHeight": True, "scale": 35, "xmlIdSeed": 20261031}
    )

    if timemap_path is not None:
        timemap = toolkit.renderToTimemap()
        target = Path(timemap_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(timemap, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    pages: list[Path] = []
    svg_prefix = Path(svg_prefix)
    svg_prefix.parent.mkdir(parents=True, exist_ok=True)
    for stale in svg_prefix.parent.glob(f"{svg_prefix.name}-p*.svg"):
        stale.unlink(missing_ok=True)
    for page in range(1, toolkit.getPageCount() + 1):
        svg = toolkit.renderToSVG(page)
        target = svg_prefix.with_name(f"{svg_prefix.name}-p{page}.svg")
        target.write_text(svg, encoding="utf-8")
        pages.append(target)
    return pages


def merge_pdfs(paths: list[Path], out_path: Path) -> Path:
    """Concatenate part PDFs into one file (MuseScore full-score fallback)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for path in paths:
        writer.append(str(path))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        writer.write(handle)
    return out_path
