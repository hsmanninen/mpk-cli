"""XDG-style config/cache/data paths for mpk."""

from __future__ import annotations

from pathlib import Path

from platformdirs import PlatformDirs

_APP = "mpk"
_AUTHOR = False  # keep macOS paths short (no author segment)

_dirs = PlatformDirs(appname=_APP, appauthor=_AUTHOR, roaming=False)


def config_dir() -> Path:
    return Path(_dirs.user_config_dir)


def cache_dir() -> Path:
    return Path(_dirs.user_cache_dir)


def config_file() -> Path:
    return config_dir() / "config.toml"


def filters_cache_file() -> Path:
    return cache_dir() / "filters.json"


def last_results_file() -> Path:
    """Where we stash the most recent search's events for `mpk show N`."""
    return cache_dir() / "last-results.json"
