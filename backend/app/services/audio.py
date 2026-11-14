"""Audio decoding, probing and resampling helpers.

ffmpeg is supplied by the imageio-ffmpeg wheel, so no system ffmpeg install
is required. soundfile/soxr handle WAV I/O and resampling after decoding.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from app.config import SETTINGS
from app.types import AudioInfo


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def ensure_ffmpeg_on_path() -> Path:
    """Expose imageio-ffmpeg as `ffmpeg` for libraries that shell out to it."""
    source = Path(ffmpeg_exe())
    bin_dir = SETTINGS.home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        try:
            if target.exists():
                target.unlink()
            # Same volume: hardlink instead of duplicating the ~80 MB binary.
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) not in paths:
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    return target


def ffmpeg_version() -> str:
    exe = ffmpeg_exe()
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15)
        return (out.stdout or out.stderr).splitlines()[0]
    except Exception as exc:  # pragma: no cover - diagnostic helper
        return f"unavailable ({exc})"


def decode_to_wav(
    src: Path,
    dst: Path,
    sample_rate: int = 44100,
    channels: int = 2,
) -> Path:
    """Decode any ffmpeg-supported audio file into a PCM WAV."""
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(src)
    if src.resolve() == dst.resolve():
        # WAV uploads are stored as source.wav and decoded to the same path;
        # ffmpeg refuses an output that is identical to its input.
        temporary = dst.with_name(f".{dst.stem}-{uuid4().hex}.wav")
        try:
            decode_to_wav(src, temporary, sample_rate=sample_rate, channels=channels)
            temporary.replace(dst)
        finally:
            temporary.unlink(missing_ok=True)
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vn",
        "-map_metadata",
        "-1",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg failed to decode {src}: {result.stderr.strip()}")
    return dst


def probe(path: Path) -> AudioInfo:
    path = Path(path)
    try:
        info = sf.info(str(path))
        return AudioInfo(
            path=str(path),
            sample_rate=info.samplerate,
            channels=info.channels,
            duration=info.frames / float(info.samplerate),
        )
    except Exception:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "probe.wav"
            decode_to_wav(path, wav)
            return probe(wav)


def load_audio(
    path: Path,
    sample_rate: int | None = None,
    mono: bool = False,
) -> tuple[np.ndarray, int]:
    """Load audio as float32 with shape (channels, samples).

    Returns the audio and its sample rate. If *sample_rate* differs from the
    file's rate, the signal is resampled with soxr.
    """
    data, file_rate = sf.read(str(path), always_2d=True, dtype="float32")

    if sample_rate is not None and file_rate != sample_rate:
        import soxr

        # soxr expects (samples, channels); soundfile already returns that.
        data = soxr.resample(data, file_rate, sample_rate, quality="HQ")
        file_rate = sample_rate

    audio = data.T  # (channels, samples)

    if mono and audio.shape[0] > 1:
        audio = audio.mean(axis=0, keepdims=True)

    return audio, file_rate


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> Path:
    """Write (channels, samples) float audio to a WAV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if audio.ndim == 1:
        audio = audio[None, :]
    sf.write(str(path), audio.T, sample_rate, subtype="PCM_16")
    return path


def duration_seconds(path: Path) -> float:
    return probe(path).duration


def free_space_gb(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)
