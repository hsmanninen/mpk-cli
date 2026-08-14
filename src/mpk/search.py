"""Search operations against /Calendar/CalSearch and pagination."""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote, urlencode, urlparse

from .client import BASE_URL, MpkClient
from .history import save as save_last_results
from .models import Event, EventDetail, lang_id
from .parse import (
    parse_event_detail_page,
    parse_next_event_fragment,
    parse_search_results,
    parse_total_count,
)


@dataclass
class SearchQuery:
    """A prepared search query, in the form the site expects."""

    text: str | None = None
    begin: date | None = None
    end: date | None = None
    include_ongoing: bool = True
    lang: str = "fi"

    # Backend values (already resolved via vocab)
    cities: list[str] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    specializations: list[str] = field(default_factory=list)
    target_groups: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    implementation_modes: list[str] = field(default_factory=list)

    def to_form_data(self) -> list[tuple[str, str]]:
        """Serialize to the repeat-keyed form data the server expects."""
        begin_str = (self.begin or date.today()).isoformat()
        end_str = self.end.isoformat() if self.end else ""

        fields: list[tuple[str, str]] = [
            ("CalendarViewMode", "list"),
            ("LangId", str(lang_id(self.lang))),
            ("DetailedSearchMode", "1"),
            ("BeginDateUsed", begin_str),
            ("SelectedNetworkId", "-1"),
            ("EventsCount", "0"),
            ("SearchText", self.text or ""),
            ("BeginDate", begin_str),
            ("ActualBeginDate", begin_str),
            ("EndDate", end_str),
            ("ActualEndDate", end_str),
        ]

        if self.include_ongoing:
            fields.append(("ShowOnGoingOpenEvents", "true"))
        fields.append(("ShowOnGoingOpenEvents", "false"))

        for c in self.cities:
            fields.append(("City", c))
        for d in self.districts:
            fields.append(("LocationDistricts", d))
        for s in self.specializations:
            fields.append(("SpecializationId", s))
        for t in self.target_groups:
            fields.append(("NetworkTargetGroups", t))
        for t in self.types:
            fields.append(("TypeId", t))
        for m in self.implementation_modes:
            fields.append(("ImplementationMethodId", m))

        return fields


@dataclass
class SearchResult:
    total: int | None
    events: list[Event]
    fetched: int  # count of events we actually pulled (<= total)


MAX_PAGINATION_PAGES = 1000


def _deduplicate(events: list[Event], seen: set[str]) -> list[Event]:
    """Keep the first event for each id while preserving server order."""
    unique: list[Event] = []
    for event in events:
        if event.id in seen:
            continue
        seen.add(event.id)
        unique.append(event)
    return unique


def run_search(
    query: SearchQuery,
    *,
    limit: int | None = 50,
    fetch_all: bool = False,
    pause_seconds: float = 0.4,
    on_page_fetched: Callable[[list[Event], int | None], None] | None = None,
    persist_history: bool = True,
    verbose: bool = False,
) -> SearchResult:
    """Execute a search: bootstrap session, POST filters, paginate results.

    ``on_page_fetched`` is invoked after each successful page (initial POST and
    every ``LoadNextEvent``) with ``(new_events, total)``. Useful for streaming
    partial results into an interactive UI. Exceptions from the callback are
    NOT swallowed — the caller is trusted to handle them.
    """
    with MpkClient(lang_id=lang_id(query.lang), verbose=verbose) as client:
        client.bootstrap()

        form = query.to_form_data()
        body = urlencode(form)
        r = client.post(
            "/Calendar/CalSearch",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        html = r.text

        total = parse_total_count(html)
        seen: set[str] = set()
        events = _deduplicate(parse_search_results(html), seen)
        if on_page_fetched is not None:
            on_page_fetched(list(events), total)

        target = None
        if fetch_all:
            target = total
        elif limit is not None:
            target = min(limit, total) if total is not None else limit
        elif total == 0:
            target = 0

        page_count = 0
        while target is None or len(events) < target:
            if page_count >= MAX_PAGINATION_PAGES:
                raise RuntimeError(
                    f"Pagination exceeded the safety limit of {MAX_PAGINATION_PAGES} pages"
                )
            resp = client.load_next_event()
            page_count += 1
            body = resp.text
            # Server signals end-of-stream with {"Empty":1}
            if body.strip().startswith("{"):
                try:
                    j = json.loads(body)
                except json.JSONDecodeError:
                    j = {}
                if j.get("Empty") == 1:
                    break
            more = _deduplicate(parse_next_event_fragment(body), seen)
            if not more:
                raise RuntimeError("Pagination made no progress because the server repeated events")
            events.extend(more)
            if on_page_fetched is not None:
                on_page_fetched(list(more), total)
            if target is not None and len(events) >= target:
                break
            if pause_seconds > 0:
                time.sleep(pause_seconds)

        if target is not None:
            events = events[:target]

    # Persist for `mpk show N` lookups. Best-effort; failures are non-fatal.
    if persist_history:
        with contextlib.suppress(OSError):
            save_last_results(events)

    return SearchResult(total=total, events=events, fetched=len(events))


# ---- event detail -----------------------------------------------------------


def _normalize_event_id(raw: str) -> str:
    """Accept a raw d= token, a Calendar/Event URL, or an already-decoded value."""
    raw = raw.strip()
    try:
        parsed = urlparse(raw)
        parsed_host = parsed.hostname
        parsed_port = parsed.port
    except ValueError as e:
        raise ValueError(f"Unapproved event URL: {raw!r}") from e
    if parsed.scheme or parsed.netloc or raw.startswith("//"):
        # Keep the site's double-encoded token exactly as it appears in the URL.
        if (
            parsed.scheme != "https"
            or parsed_host is None
            or parsed_host.casefold() != "koulutuskalenteri.mpk.fi"
            or parsed.username is not None
            or parsed.password is not None
            or parsed_port is not None
            or parsed.path != "/Calendar/Event"
        ):
            raise ValueError(f"Unapproved event URL: {raw!r}")
        for part in parsed.query.split("&"):
            key, separator, value = part.partition("=")
            if separator and key == "d":
                return value
        return ""
    return raw


def fetch_event_detail(
    event_id_or_url: str,
    *,
    lang: str = "fi",
    verbose: bool = False,
) -> EventDetail:
    ev_id = _normalize_event_id(event_id_or_url)
    if not ev_id:
        raise ValueError(f"Could not extract event id from {event_id_or_url!r}")

    # The href in search results already contains a URL-encoded token
    # (e.g. "SYNTHETIC%252fTOKEN%253d"). If a user passed the raw form we should not
    # double-encode.
    encoded = ev_id if "%" in ev_id else quote(ev_id, safe="")
    path = f"/Calendar/Event?d={encoded}"

    with MpkClient(lang_id=lang_id(lang), verbose=verbose) as client:
        client.bootstrap()
        r = client.get(path)
        html = r.text

    detail = parse_event_detail_page(html)
    detail.id = ev_id
    detail.url = f"{BASE_URL}{path}"
    return detail
