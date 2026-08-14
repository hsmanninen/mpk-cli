from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from mpk.tui import clipboard


def test_copy_uses_clipboard_when_available(monkeypatch) -> None:
    copied = []
    monkeypatch.setitem(sys.modules, "pyperclip", SimpleNamespace(copy=copied.append))

    assert clipboard.copy("event URL") == "Kopioitu leikepöydälle."
    assert copied == ["event URL"]


def test_copy_falls_back_to_file_and_creates_parent(tmp_path, monkeypatch) -> None:
    path = tmp_path / "missing" / "yank.txt"
    monkeypatch.setitem(
        sys.modules,
        "pyperclip",
        SimpleNamespace(copy=lambda _text: (_ for _ in ()).throw(RuntimeError("unavailable"))),
    )
    monkeypatch.setattr(clipboard, "_yank_path", lambda: path)

    message = clipboard.copy("event URL")

    assert path.read_text(encoding="utf-8") == "event URL\n"
    assert str(path) in message


def test_copy_reports_fallback_write_failure(tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocked", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "pyperclip",
        SimpleNamespace(copy=lambda _text: (_ for _ in ()).throw(RuntimeError("unavailable"))),
    )
    monkeypatch.setattr(clipboard, "_yank_path", lambda: blocker / "yank.txt")

    assert clipboard.copy("event URL").startswith("Kopiointi epäonnistui:")


def test_yank_path_is_pure(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "missing-cache"
    monkeypatch.setattr(clipboard, "cache_dir", lambda: cache)

    assert clipboard._yank_path() == cache / "yank.txt"
    assert not cache.exists()


def test_fallback_write_is_atomic_on_replace_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "yank.txt"
    path.write_text("existing\n", encoding="utf-8")
    monkeypatch.setattr(
        clipboard.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        clipboard._write_fallback(path, "replacement\n")

    assert path.read_text(encoding="utf-8") == "existing\n"
    assert list(tmp_path.glob(".yank.*.tmp")) == []
