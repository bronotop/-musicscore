"""Download the MuScriptor medium weights with parallel HTTP range requests.

The official MuScriptor repositories are gated behind a Hugging Face login and
the CC BY-NC 4.0 license. By default this helper uses the public mirror
``BEDO97/muscriptor-medium`` for networks where the official repo is not
accessible. You can override it with ``--url``.

Usage:
    python scripts/fetch_muscriptor_mirror.py \
        --proxy http://127.0.0.1:7890

    python scripts/fetch_muscriptor_mirror.py \
        --url https://huggingface.co/<user>/<repo>/resolve/main/model.safetensors

Weights are downloaded to ``$MUSIC2SCORE_HOME/models/muscriptor/muscriptor-medium``
(the default home is ``<repository>/runtime``).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import time
from pathlib import Path

import requests

DEFAULT_URL = "https://huggingface.co/BEDO97/muscriptor-medium/resolve/main/model.safetensors"
TOTAL = 1_228_144_472  # verified size of model.safetensors


def download(out: Path, proxy: str | None, workers: int = 16, url: str = DEFAULT_URL) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size == TOTAL:
        print(f"already complete: {out}")
        return out

    proxies = {"http": proxy, "https": proxy} if proxy else None
    with open(out, "wb") as handle:
        handle.truncate(TOTAL)

    per_worker = (TOTAL + workers - 1) // workers

    def fetch(index: int) -> int:
        start = index * per_worker
        end = min(TOTAL - 1, start + per_worker - 1)
        if start >= TOTAL:
            return 0
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                response = requests.get(
                    url,
                    headers={"Range": f"bytes={start}-{end}"},
                    proxies=proxies,
                    stream=True,
                    timeout=1800,
                )
                response.raise_for_status()
                written = 0
                with open(out, "r+b") as handle:
                    handle.seek(start)
                    for block in response.iter_content(4 * 1024 * 1024):
                        if block:
                            handle.write(block)
                            written += len(block)
                if written != end - start + 1:
                    raise RuntimeError(f"short range: {written} != {end - start + 1}")
                return written
            except Exception as exc:  # retry transient proxy/CDN failures
                last_error = exc
                print(f"range {index} attempt {attempt} failed: {exc}", flush=True)
                time.sleep(3)
        raise RuntimeError(f"range {index} failed: {last_error}")

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        sizes = list(pool.map(fetch, range(workers)))
    elapsed = time.time() - started
    print(
        f"downloaded {sum(sizes)} bytes in {elapsed:.1f}s "
        f"({sum(sizes) / 1048576 / elapsed:.2f} MB/s)"
    )

    actual = out.stat().st_size
    if actual != TOTAL:
        raise RuntimeError(f"size mismatch: {actual} != {TOTAL}")

    digest = hashlib.sha256()
    with open(out, "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    print(f"sha256 {digest.hexdigest()}")
    return out


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    home = Path(os.environ.get("MUSIC2SCORE_HOME", repo_root / "runtime")).expanduser()
    default_out = home / "models" / "muscriptor" / "muscriptor-medium"

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(default_out))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.url == DEFAULT_URL:
        print(
            "note: using the third-party mirror BEDO97/muscriptor-medium. "
            "The official MuScriptor repo is gated and requires a Hugging Face login."
        )
    target = Path(args.out) / "model.safetensors"
    download(target, args.proxy, args.workers, args.url)


if __name__ == "__main__":
    main()
