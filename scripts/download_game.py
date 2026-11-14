#!/usr/bin/env python3
"""Download a GAME ONNX checkpoint for the vocal-melody adapter.

GAME is MIT-licensed (code and released checkpoints):
    https://github.com/openvpi/GAME

Examples:
    python scripts/download_game.py --size medium
    python scripts/download_game.py --size medium --dest runtime/models/game
    python scripts/download_game.py --check --dest runtime/models/game

The script tries GitHub first and falls back to public mirrors. Weights are
written under ``$MUSIC2SCORE_HOME/models/game`` by default (the default home is
``<repository>/runtime``).
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "v1.0.3"
ASSETS = {
    "small": "GAME-1.0.3-small-onnx.zip",
    "medium": "GAME-1.0.3-medium-onnx.zip",
    "large": "GAME-1.0.3-large-onnx.zip",
}
BASE_URL = f"https://github.com/openvpi/GAME/releases/download/{RELEASE}"
MIRRORS = (
    "",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
)
KNOWN_SHA256 = {
    # Verified against the v1.0.3 release asset on 2026-11-07.
    "medium": "5b7a21e64c6310efac399f5d12838fffa70565be162436b5a4a65f290721e7d8",
}
REQUIRED = ("config.json", "encoder.onnx", "segmenter.onnx", "estimator.onnx")


def default_destination() -> Path:
    home = os.environ.get("MUSIC2SCORE_HOME")
    if home:
        return Path(home).expanduser() / "models" / "game"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.config import SETTINGS

        return Path(SETTINGS.models_dir) / "game"
    except Exception:
        pass
    return Path(__file__).resolve().parents[1] / "runtime" / "models" / "game"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_opener(cookie_file: str | None):
    handlers = []
    if cookie_file:
        path = Path(cookie_file).expanduser()
        if path.is_file():
            jar = http.cookiejar.MozillaCookieJar(str(path))
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
                handlers.append(urllib.request.HTTPCookieProcessor(jar))
            except Exception as exc:
                print(f"warning: could not read cookies {path}: {exc}", file=sys.stderr)
        else:
            print(f"warning: cookie file not found: {path}", file=sys.stderr)
    return urllib.request.build_opener(*handlers)


def download(url: str, destination: Path, opener) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "music2score-game-downloader/1.0",
            "Accept": "application/octet-stream",
        },
    )
    with opener.open(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        temporary = destination.with_suffix(destination.suffix + ".part")
        with temporary.open("wb") as handle:
            received = 0
            last_percent = -10
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if total:
                    percent = int(received * 100 / total)
                    if percent >= last_percent + 5:
                        print(f"  {percent:3d}%  {received / 1048576:.1f} MiB")
                        last_percent = percent
        temporary.replace(destination)
    if total and destination.stat().st_size != total:
        raise IOError(
            f"incomplete download: {destination.stat().st_size} of {total} bytes"
        )


def find_export(root: Path) -> Path | None:
    candidates = [root]
    candidates.extend(sorted(path for path in root.glob("GAME-*") if path.is_dir()))
    for candidate in candidates:
        if all((candidate / name).is_file() for name in REQUIRED):
            return candidate
    return None


def verify_export(export: Path) -> None:
    print(f"model directory: {export}")
    for name in REQUIRED:
        path = export / name
        print(f"  {name:16s} {path.stat().st_size:>12,d} bytes  {sha256(path)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download GAME ONNX checkpoints")
    parser.add_argument("--size", choices=sorted(ASSETS), default="medium")
    parser.add_argument("--dest", type=Path, default=default_destination())
    parser.add_argument("--cookie-file", default=None, help="Netscape cookie file (optional)")
    parser.add_argument("--mirror", choices=["auto", "github", "ghproxy", "ghproxy.net"], default="auto")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--force", action="store_true", help="re-download an existing zip")
    parser.add_argument("--check", action="store_true", help="only verify an existing checkout")
    args = parser.parse_args()

    destination = args.dest.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    existing = find_export(destination)
    if args.check:
        if existing is None:
            print(f"no complete GAME export under {destination}", file=sys.stderr)
            return 1
        verify_export(existing)
        return 0

    asset = ASSETS[args.size]
    archive = destination / asset
    if existing is not None and not args.force:
        print(f"GAME already present: {existing}")
        verify_export(existing)
        return 0

    if args.mirror == "auto":
        mirrors = MIRRORS
    elif args.mirror == "github":
        mirrors = ("",)
    else:
        mirrors = (f"https://{args.mirror}/",)

    opener = build_opener(args.cookie_file)
    errors = []
    for prefix in mirrors:
        url = f"{prefix}{BASE_URL}/{asset}"
        print(f"downloading {url}")
        try:
            download(url, archive, opener)
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{url}: {exc}")
            print(f"  failed: {exc}", file=sys.stderr)
    else:
        print("all download sources failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    digest = sha256(archive)
    print(f"archive sha256: {digest}")
    expected = KNOWN_SHA256.get(args.size)
    if expected and digest != expected:
        print(
            f"error: expected {expected} for {args.size}; refusing to extract",
            file=sys.stderr,
        )
        return 1
    if not expected:
        print(
            f"warning: no pinned SHA-256 for size '{args.size}'; "
            "check the release page before using this checkpoint",
            file=sys.stderr,
        )

    with zipfile.ZipFile(archive) as bundle:
        root = destination.resolve()
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                print(f"error: unsafe archive member: {member.filename}", file=sys.stderr)
                return 1
        bundle.extractall(destination)

    export = find_export(destination)
    if export is None:
        print(f"archive extracted but no complete export found under {destination}", file=sys.stderr)
        return 1
    verify_export(export)
    print("license: MIT (OpenVPI GAME code and released checkpoints)")
    print("set VOCAL_GAME_MODEL to this directory to force the model path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
