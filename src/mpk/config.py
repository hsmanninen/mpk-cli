"""User configuration loading (TOML)."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from textual.theme import BUILTIN_THEMES

from .paths import config_file


@dataclass
class CacheConfig:
    filters_ttl_days: int = 30
    allow_network_refresh: bool = True


@dataclass
class DefaultFiltersConfig:
    cities: list[str] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    specializations: list[str] = field(default_factory=list)
    target_groups: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)

    def any_set(self) -> bool:
        return any(
            (
                self.cities,
                self.districts,
                self.specializations,
                self.target_groups,
                self.modes,
                self.types,
            )
        )


@dataclass
class DefaultsConfig:
    lang: str = "fi"
    include_ongoing: bool = True
    limit: int = 50
    filters: DefaultFiltersConfig = field(default_factory=DefaultFiltersConfig)


@dataclass
class TuiConfig:
    enabled: bool = True
    theme: str = "auto"  # "auto" | "light" | "dark"
    page_size: int = 50
    show_registration_status: bool = True


@dataclass
class Config:
    cache: CacheConfig = field(default_factory=CacheConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    tui: TuiConfig = field(default_factory=TuiConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults if missing/invalid."""
    p = path or config_file()
    if not p.exists():
        return Config()
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return Config()

    def table(name: str) -> dict:
        value = raw.get(name, {})
        return value if isinstance(value, dict) else {}

    def integer(values: dict, key: str, default: int, *, minimum: int = 1) -> int:
        value = values.get(key, default)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= minimum
            else default
        )

    def boolean(values: dict, key: str, default: bool) -> bool:
        value = values.get(key, default)
        return value if isinstance(value, bool) else default

    cache_raw = table("cache")
    defaults_raw = table("defaults")
    filters_raw = defaults_raw.get("filters", {})
    if not isinstance(filters_raw, dict):
        filters_raw = {}
    tui_raw = table("tui")

    def strings(values: dict, key: str) -> list[str]:
        value = values.get(key, [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item]

    lang = defaults_raw.get("lang", "fi")
    if lang not in {"fi", "en", "sv"}:
        lang = "fi"
    theme = tui_raw.get("theme", "auto")
    if theme in {"light", "dark"}:
        pass
    elif not isinstance(theme, str) or theme not in BUILTIN_THEMES:
        theme = "auto"

    return Config(
        cache=CacheConfig(
            filters_ttl_days=integer(cache_raw, "filters_ttl_days", 30),
            allow_network_refresh=boolean(cache_raw, "allow_network_refresh", True),
        ),
        defaults=DefaultsConfig(
            lang=lang,
            include_ongoing=boolean(defaults_raw, "include_ongoing", True),
            limit=integer(defaults_raw, "limit", 50),
            filters=DefaultFiltersConfig(
                cities=strings(filters_raw, "cities"),
                districts=strings(filters_raw, "districts"),
                specializations=strings(filters_raw, "specializations"),
                target_groups=strings(filters_raw, "target_groups"),
                modes=strings(filters_raw, "modes"),
                types=strings(filters_raw, "types"),
            ),
        ),
        tui=TuiConfig(
            enabled=boolean(tui_raw, "enabled", True),
            theme=theme,
            page_size=integer(tui_raw, "page_size", 50),
            show_registration_status=boolean(tui_raw, "show_registration_status", True),
        ),
    )


def save_tui_theme(theme: str, path: Path | None = None) -> None:
    """Atomically update only ``[tui].theme`` while preserving the user's TOML."""
    target = path or config_file()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""

    value = f'theme = "{_escape_toml(theme)}"'
    section = re.search(r"(?ms)^\[tui\][ \t]*(?:#.*)?$.*?(?=^\[|\Z)", text)
    if section is None:
        separator = (
            "" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
        )
        updated = f"{text}{separator}[tui]\n{value}\n"
    else:
        block = section.group(0)
        if re.search(r"(?m)^\s*theme\s*=.*$", block):
            new_block = re.sub(r"(?m)^\s*theme\s*=.*$", value, block, count=1)
        else:
            first_line, remainder = block.split("\n", 1)
            new_block = f"{first_line}\n{value}\n{remainder}"
        updated = text[: section.start()] + new_block + text[section.end() :]

    _atomic_write(target, updated)


def save_default_filters(filters: dict[str, list[str]], path: Path | None = None) -> None:
    """Atomically save backend filter values under ``[defaults.filters]``."""
    target = path or config_file()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""

    lines = ["[defaults.filters]"]
    for key in ("cities", "districts", "specializations", "target_groups", "modes", "types"):
        values = filters.get(key, [])
        encoded = ", ".join(f'"{_escape_toml(value)}"' for value in values)
        lines.append(f"{key} = [{encoded}]")
    updated = _replace_section(text, "defaults.filters", "\n".join(lines) + "\n")
    _atomic_write(target, updated)


def reset_default_filters(path: Path | None = None) -> None:
    """Remove saved startup filters while preserving all other configuration."""
    target = path or config_file()
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    section = re.search(r"(?ms)^\[defaults\.filters\][ \t]*(?:#.*)?$.*?(?=^\[|\Z)", text)
    if section is None:
        return
    updated = text[: section.start()] + text[section.end() :]
    _atomic_write(target, updated)


def _escape_toml(value: str) -> str:
    escapes = {
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
        '"': '\\"',
        "\\": "\\\\",
    }
    return "".join(
        escapes.get(char, f"\\u{ord(char):04X}" if ord(char) < 0x20 or ord(char) == 0x7F else char)
        for char in value
    )


def _replace_section(text: str, name: str, block: str) -> str:
    section = re.search(rf"(?ms)^\[{re.escape(name)}\][ \t]*(?:#.*)?$.*?(?=^\[|\Z)", text)
    if section is not None:
        return text[: section.start()] + block + text[section.end() :]
    separator = "" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
    return f"{text}{separator}{block}"


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        _fsync_directory(target.parent)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _fsync_directory(path: Path) -> None:
    """Best-effort persistence of a completed rename on POSIX."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    with contextlib.suppress(OSError):
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
