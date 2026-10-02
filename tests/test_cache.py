from app import config
from app.cache import Cache


def test_miss_then_hit(tmp_path):
    cache = Cache(tmp_path / "cache.db")
    assert cache.get("a/b", "sha1") is None
    cache.put("a/b", "sha1", {"x": 1})
    assert cache.get("a/b", "sha1") == {"x": 1}
    assert cache.get("a/b", "sha2") is None      # different commit
    assert cache.get("a/c", "sha1") is None      # different repo


def test_survives_a_restart(tmp_path):
    Cache(tmp_path / "cache.db").put("a/b", "sha1", {"x": 1})
    assert Cache(tmp_path / "cache.db").get("a/b", "sha1") == {"x": 1}


def test_new_analysis_version_ignores_old_results(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "cache.db")
    cache.put("a/b", "sha1", {"x": 1})
    monkeypatch.setattr(config, "ANALYSIS_VERSION", config.ANALYSIS_VERSION + 1)
    assert cache.get("a/b", "sha1") is None


def test_creates_missing_folders(tmp_path):
    Cache(tmp_path / "new" / "dir" / "cache.db")
    assert (tmp_path / "new" / "dir" / "cache.db").exists()
