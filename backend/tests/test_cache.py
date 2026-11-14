from __future__ import annotations

from app.pipeline.cache import StageCache, StageManifest, cache_key


def test_key_is_stable_and_param_sensitive(tmp_path):
    source = tmp_path / "input.wav"
    source.write_bytes(b"hello world")

    first = cache_key("ingest", [source], {"sr": 44100})
    second = cache_key("ingest", [source], {"sr": 44100})
    changed = cache_key("ingest", [source], {"sr": 48000})

    assert first == second
    assert first != changed


def test_key_changes_when_file_changes(tmp_path):
    source = tmp_path / "input.wav"
    source.write_bytes(b"a")
    first = cache_key("ingest", [source], {})
    source.write_bytes(b"b")
    second = cache_key("ingest", [source], {})
    assert first != second


def test_manifest_roundtrip(tmp_path):
    cache = StageCache(tmp_path / "cache")
    manifest = StageManifest(
        stage="ingest",
        key="abc123",
        outputs={"audio": "source.wav"},
        metrics={"duration": 12.5},
        params={"sample_rate": 44100},
    )
    cache.save(manifest)

    loaded = cache.load("ingest", "abc123")
    assert loaded is not None
    assert loaded.outputs == {"audio": "source.wav"}
    assert loaded.metrics["duration"] == 12.5

    assert cache.load("ingest", "different") is None
    assert cache.load("missing", "abc123") is None
