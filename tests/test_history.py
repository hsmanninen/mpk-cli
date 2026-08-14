from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from mpk import history
from mpk.models import Event


@pytest.fixture()
def sample_events() -> list[Event]:
    return [
        Event(
            id="abc%253d",
            url="https://koulutuskalenteri.mpk.fi/Calendar/Event?d=abc%253d",
            title="Ensiapu-kurssi",
            start=datetime(2026, 9, 2, 17, 0),
            end=datetime(2026, 9, 2, 20, 0),
            city="Mikkeli",
            registration_status="Julkaistu",
        ),
        Event(
            id="def%253d",
            url="https://koulutuskalenteri.mpk.fi/Calendar/Event?d=def%253d",
            title="Toka",
            start=None,
            end=None,
        ),
    ]


def test_save_and_load_roundtrip(sample_events: list[Event], tmp_path: Path) -> None:
    p = tmp_path / "last.json"
    history.save(sample_events, path=p)
    loaded = history.load(path=p)
    assert loaded is not None
    assert len(loaded.events) == 2
    assert loaded.events[0].title == "Ensiapu-kurssi"
    assert loaded.events[0].start == datetime(2026, 9, 2, 17, 0)
    assert loaded.events[1].city is None


def test_resolve_row_ok(sample_events: list[Event], tmp_path: Path) -> None:
    p = tmp_path / "last.json"
    history.save(sample_events, path=p)
    ev = history.resolve_row(2, path=p)
    assert ev.title == "Toka"


def test_resolve_row_out_of_range(sample_events: list[Event], tmp_path: Path) -> None:
    p = tmp_path / "last.json"
    history.save(sample_events, path=p)
    with pytest.raises(LookupError, match="out of range"):
        history.resolve_row(3, path=p)
    with pytest.raises(LookupError, match="out of range"):
        history.resolve_row(0, path=p)


def test_resolve_row_missing_cache(tmp_path: Path) -> None:
    with pytest.raises(LookupError, match="No previous search"):
        history.resolve_row(1, path=tmp_path / "nope.json")


def test_load_missing_cache(tmp_path: Path) -> None:
    assert history.load(path=tmp_path / "nope.json") is None


def test_load_corrupt_cache(tmp_path: Path) -> None:
    p = tmp_path / "last.json"
    p.write_text("{not json", encoding="utf-8")
    assert history.load(path=p) is None


@pytest.mark.parametrize(
    "payload",
    ["[]", '"text"', '{"schema": "one"}', '{"schema": true}', '{"schema": 1, "events": [null]}'],
)
def test_load_rejects_malformed_state(tmp_path: Path, payload: str) -> None:
    p = tmp_path / "last.json"
    p.write_text(payload, encoding="utf-8")
    assert history.load(path=p) is None


def test_save_creates_parent_directories(sample_events: list[Event], tmp_path: Path) -> None:
    p = tmp_path / "nested" / "cache" / "last.json"
    history.save(sample_events, path=p)
    assert history.load(path=p) is not None
