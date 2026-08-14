from __future__ import annotations

from types import SimpleNamespace

from mpk import paths


def test_path_queries_do_not_create_directories(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "missing-config"
    cache_dir = tmp_path / "missing-cache"
    monkeypatch.setattr(
        paths,
        "_dirs",
        SimpleNamespace(user_config_dir=str(config_dir), user_cache_dir=str(cache_dir)),
    )

    assert paths.config_dir() == config_dir
    assert paths.cache_dir() == cache_dir
    assert paths.config_file() == config_dir / "config.toml"
    assert paths.filters_cache_file() == cache_dir / "filters.json"
    assert paths.last_results_file() == cache_dir / "last-results.json"
    assert not config_dir.exists()
    assert not cache_dir.exists()
