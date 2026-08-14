"""Persistent stash of the most recent search's events.

Enables `mpk show N` where N is a row index from the last `mpk search` output.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Event
from .paths import last_results_file

SCHEMA_VERSION = 1


@dataclass
class LastResults:
    saved_at: datetime
    events: list[Event]

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "saved_at": self.saved_at.isoformat(),
            "events": [e.to_dict() for e in self.events],
        }


def _from_json(data: dict) -> LastResults:
    events: list[Event] = []
    for raw in data.get("events", []) or []:
        start = datetime.fromisoformat(raw["start"]) if raw.get("start") else None
        end = datetime.fromisoformat(raw["end"]) if raw.get("end") else None
        events.append(
            Event(
                id=str(raw.get("id", "")),
                url=str(raw.get("url", "")),
                title=str(raw.get("title", "")),
                start=start,
                end=end,
                city=raw.get("city"),
                location=raw.get("location"),
                mode=raw.get("mode"),
                topics=list(raw.get("topics", []) or []),
                target_groups=list(raw.get("target_groups", []) or []),
                registration_status=raw.get("registration_status"),
            )
        )
    saved_at = (
        datetime.fromisoformat(data["saved_at"]) if data.get("saved_at") else datetime.now(UTC)
    )
    return LastResults(saved_at=saved_at, events=events)


def save(events: list[Event], *, path: Path | None = None) -> Path:
    p = path or last_results_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = LastResults(saved_at=datetime.now(UTC), events=events).to_json()

    fd, tmp = tempfile.mkstemp(prefix=".last-results.", suffix=".json.tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        _fsync_directory(p.parent)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return p


def load(*, path: Path | None = None) -> LastResults | None:
    p = path or last_results_file()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or type(data.get("schema")) is not int:
        return None
    if data["schema"] != SCHEMA_VERSION:
        return None
    try:
        return _from_json(data)
    except Exception:
        return None


def resolve_row(row_number: int, *, path: Path | None = None) -> Event:
    """Look up the Nth event (1-indexed) from the most recent search."""
    last = load(path=path)
    if last is None or not last.events:
        raise LookupError(
            "No previous search results found. Run `mpk search …` first, "
            "or pass the event URL directly."
        )
    if row_number < 1 or row_number > len(last.events):
        raise LookupError(
            f"Row {row_number} out of range (last search had {len(last.events)} results)."
        )
    return last.events[row_number - 1]


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
