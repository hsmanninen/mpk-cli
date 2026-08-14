from __future__ import annotations

import tomllib

import pytest

from mpk import config as config_module
from mpk.config import (
    Config,
    load_config,
    reset_default_filters,
    save_default_filters,
    save_tui_theme,
)


def test_load_config_accepts_valid_values(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[defaults]
lang = "en"
include_ongoing = false
limit = 12
[tui]
theme = "dark"
page_size = 25
show_registration_status = false
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.defaults.lang == "en"
    assert config.defaults.include_ongoing is False
    assert config.defaults.limit == 12
    assert config.tui.theme == "dark"
    assert config.tui.page_size == 25
    assert config.tui.show_registration_status is False


def test_load_config_falls_back_for_wrong_types(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
cache = "not a table"
[defaults]
lang = "de"
include_ongoing = "false"
limit = -1
[tui]
enabled = "false"
theme = "neon"
page_size = "many"
""",
        encoding="utf-8",
    )
    assert load_config(path) == Config()


def test_save_tui_theme_preserves_other_configuration(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """# Keep this comment
[defaults]
lang = "en"

[tui]
enabled = false
theme = "dark"
page_size = 25
""",
        encoding="utf-8",
    )

    save_tui_theme("nord", path)

    text = path.read_text(encoding="utf-8")
    assert "# Keep this comment" in text
    assert "enabled = false" in text
    assert "page_size = 25" in text
    assert 'theme = "nord"' in text
    assert load_config(path).tui.theme == "nord"


def test_save_and_reset_default_filters(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[defaults]\nlang = "en"\n\n[tui]\ntheme = "dark"\n', encoding="utf-8")

    save_default_filters(
        {
            "cities": ["Helsinki"],
            "districts": ["1000"],
            "specializations": ["1002"],
            "target_groups": [],
            "modes": ["1"],
            "types": ["12"],
        },
        path,
    )

    config = load_config(path)
    assert config.defaults.filters.cities == ["Helsinki"]
    assert config.defaults.filters.specializations == ["1002"]
    assert config.defaults.filters.modes == ["1"]
    assert config.tui.theme == "dark"

    reset_default_filters(path)
    config = load_config(path)
    assert not config.defaults.filters.any_set()
    assert config.defaults.lang == "en"
    assert config.tui.theme == "dark"


def test_save_default_filters_escapes_toml_basic_strings(tmp_path) -> None:
    path = tmp_path / "nested" / "config.toml"
    values = ['quote " slash \\', "line\nbreak", "tab\tbackspace\b", "nul\0 delete\x7f"]

    save_default_filters({"cities": values}, path)

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["defaults"]["filters"]["cities"] == values


def test_save_tui_theme_creates_parent_and_escapes_controls(tmp_path) -> None:
    path = tmp_path / "nested" / "config.toml"

    save_tui_theme("line\nbreak", path)

    assert tomllib.loads(path.read_text(encoding="utf-8"))["tui"]["theme"] == "line\nbreak"


@pytest.mark.skipif(config_module.os.name != "posix", reason="directory fsync is POSIX-only")
def test_directory_fsync_is_best_effort(tmp_path, monkeypatch) -> None:
    def fail_open(_path, _flags):
        raise OSError("directory fsync unsupported")

    monkeypatch.setattr(config_module.os, "open", fail_open)
    config_module._fsync_directory(tmp_path)


def test_atomic_write_fsyncs_parent_after_replace(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.toml"
    synced = []
    monkeypatch.setattr(config_module, "_fsync_directory", synced.append)

    save_tui_theme("dark", path)

    assert synced == [tmp_path]


def test_writers_preserve_sections_with_inline_comments(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[tui] # preferences\ntheme = "light"\n\n'
        '[defaults.filters] # selected values\ncities = ["Old"]\n',
        encoding="utf-8",
    )

    save_tui_theme("dark", path)
    save_default_filters({"cities": ["Helsinki"]}, path)

    text = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    assert text.count("[tui]") == 1
    assert text.count("[defaults.filters]") == 1
    assert parsed["tui"]["theme"] == "dark"
    assert parsed["defaults"]["filters"]["cities"] == ["Helsinki"]
