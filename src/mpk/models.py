"""Domain models for events and filter vocabulary."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

# ---- language ---------------------------------------------------------------

LANG_TO_ID: dict[str, int] = {"fi": 0, "en": 1, "sv": 2}
ID_TO_LANG: dict[int, str] = {v: k for k, v in LANG_TO_ID.items()}


def lang_id(lang: str) -> int:
    try:
        return LANG_TO_ID[lang.lower()]
    except KeyError as e:
        raise ValueError(f"Unknown language {lang!r}; expected one of {list(LANG_TO_ID)}") from e


# ---- events -----------------------------------------------------------------


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@dataclass
class Event:
    id: str
    url: str
    title: str
    start: datetime | None = None
    end: datetime | None = None
    city: str | None = None
    location: str | None = None
    mode: str | None = None
    topics: list[str] = field(default_factory=list)
    target_groups: list[str] = field(default_factory=list)
    registration_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = _iso(self.start)
        d["end"] = _iso(self.end)
        return d


@dataclass
class EventDetail(Event):
    description: str | None = None
    goals: str | None = None
    duration: str | None = None
    price: str | None = None
    organizer: str | None = None
    contact: str | None = None
    target_group_note: str | None = None
    registration_url: str | None = None
    registration_deadline: str | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"] = _iso(self.start)
        d["end"] = _iso(self.end)
        return d


# ---- vocabulary -------------------------------------------------------------


@dataclass
class FilterOption:
    """A single filter option: backend value + display label."""

    value: str  # what to POST (id or raw string)
    label: str  # human-readable name

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


@dataclass
class FilterVocab:
    """All filter dimensions parsed from /Calendar/, for a specific language."""

    lang: str
    cities: list[FilterOption] = field(default_factory=list)
    districts: list[FilterOption] = field(default_factory=list)
    specializations: list[FilterOption] = field(default_factory=list)
    target_groups: list[FilterOption] = field(default_factory=list)
    types: list[FilterOption] = field(default_factory=list)
    implementation_modes: list[FilterOption] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lang": self.lang,
            "cities": [o.to_dict() for o in self.cities],
            "districts": [o.to_dict() for o in self.districts],
            "specializations": [o.to_dict() for o in self.specializations],
            "target_groups": [o.to_dict() for o in self.target_groups],
            "types": [o.to_dict() for o in self.types],
            "implementation_modes": [o.to_dict() for o in self.implementation_modes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilterVocab:
        def _mk(items: list[dict[str, str]]) -> list[FilterOption]:
            return [FilterOption(value=str(i["value"]), label=str(i["label"])) for i in items]

        return cls(
            lang=str(data.get("lang", "fi")),
            cities=_mk(data.get("cities", [])),
            districts=_mk(data.get("districts", [])),
            specializations=_mk(data.get("specializations", [])),
            target_groups=_mk(data.get("target_groups", [])),
            types=_mk(data.get("types", [])),
            implementation_modes=_mk(data.get("implementation_modes", [])),
        )
