"""Clipboard helpers with a graceful pyperclip fallback."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from ..paths import cache_dir


def copy(text: str) -> str:
    """Copy text to the system clipboard, or fall back to a file.

    Returns a short user-facing status string suitable for a toast/notify.
    """
    try:
        import pyperclip  # local import: keeps startup fast + optional

        pyperclip.copy(text)
        return "Kopioitu leikepöydälle."
    except Exception:
        path = _yank_path()
        try:
            _write_fallback(path, text + "\n")
            return f"Leikepöytä ei käytettävissä — tallennettu: {path}"
        except OSError as e:
            return f"Kopiointi epäonnistui: {e}"


def _yank_path() -> Path:
    return cache_dir() / "yank.txt"


def _write_fallback(path: Path, text: str) -> None:
    """Atomically replace the clipboard fallback file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".yank.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
