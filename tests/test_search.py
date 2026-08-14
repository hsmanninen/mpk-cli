from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from mpk.models import Event
from mpk.search import SearchQuery, _normalize_event_id, fetch_event_detail, run_search


def test_normalize_event_url_preserves_double_encoded_token() -> None:
    token = "SYNTHETIC%252fTOKEN%253d"
    url = f"https://koulutuskalenteri.mpk.fi/Calendar/Event?x=1&d={token}&lang=fi"
    assert _normalize_event_id(url) == token


@pytest.mark.parametrize(
    "url",
    [
        "http://koulutuskalenteri.mpk.fi/Calendar/Event?d=token",
        "https://evil.example/Calendar/Event?d=token",
        "https://koulutuskalenteri.mpk.fi.evil.example/Calendar/Event?d=token",
        "https://koulutuskalenteri.mpk.fi/Other?d=token",
    ],
)
def test_normalize_event_url_rejects_unapproved_url(url: str) -> None:
    with pytest.raises(ValueError, match="Unapproved event URL"):
        _normalize_event_id(url)


def test_detail_fetch_rejects_http_200_error_page(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def get(self, path: str) -> httpx.Response:
            return httpx.Response(200, text="<html><title>Maintenance</title></html>")

    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)

    with pytest.raises(ValueError, match="does not look like"):
        fetch_event_detail("SYNTHETIC-TOKEN")


def test_search_can_defer_history_persistence(monkeypatch) -> None:
    saved: list[list[Event]] = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def post(self, *args, **kwargs) -> httpx.Response:
            return httpx.Response(200, text="<h2>Events (0)</h2>")

    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)
    monkeypatch.setattr("mpk.search.save_last_results", saved.append)

    run_search(SearchQuery(), persist_history=False)

    assert saved == []


def test_fetch_all_paginates_when_total_is_unknown(monkeypatch, tmp_path) -> None:
    responses = iter(
        [
            httpx.Response(200, text='<div class="koulutus_lista"></div>'),
            httpx.Response(200, text='{"Empty":1}'),
        ]
    )

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def post(self, *args, **kwargs) -> httpx.Response:
            return httpx.Response(200, text="<h2>Events (1)</h2><div class='koulutus_lista'></div>")

        def load_next_event(self) -> httpx.Response:
            return next(responses)

    event = Event(
        id="id",
        url="https://example.test/event",
        title="Event",
        start=datetime(2026, 8, 12),
    )
    pages = iter([[event]])
    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)
    monkeypatch.setattr("mpk.search.parse_search_results", lambda html: [])
    monkeypatch.setattr("mpk.search.parse_total_count", lambda html: None)
    monkeypatch.setattr("mpk.search.parse_next_event_fragment", lambda html: next(pages))
    monkeypatch.setattr("mpk.search.save_last_results", lambda events: None)

    result = run_search(SearchQuery(), fetch_all=True, pause_seconds=0)

    assert result.events == [event]
    assert result.total is None


def test_recognizable_empty_search_does_not_paginate(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def post(self, *args, **kwargs) -> httpx.Response:
            return httpx.Response(200, text="<h2>Events (0)</h2>")

        def load_next_event(self) -> httpx.Response:
            raise AssertionError("empty searches must not paginate")

    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)
    monkeypatch.setattr("mpk.search.save_last_results", lambda events: None)

    result = run_search(SearchQuery(), pause_seconds=0)

    assert result.total == 0
    assert result.events == []


def test_pagination_deduplicates_in_order_and_reports_only_progress(monkeypatch) -> None:
    first = Event(id="a", url="https://example.test/a", title="A")
    second = Event(id="b", url="https://example.test/b", title="B")
    third = Event(id="c", url="https://example.test/c", title="C")
    fragments = iter(["page-1", "page-2"])
    parsed_pages = iter([[first, second], [second, third]])

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def post(self, *args, **kwargs) -> httpx.Response:
            return httpx.Response(200, text="initial")

        def load_next_event(self) -> httpx.Response:
            return httpx.Response(200, text=next(fragments))

    callbacks: list[list[str]] = []
    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)
    monkeypatch.setattr("mpk.search.parse_total_count", lambda html: 3)
    monkeypatch.setattr("mpk.search.parse_search_results", lambda html: [first, first])
    monkeypatch.setattr("mpk.search.parse_next_event_fragment", lambda html: next(parsed_pages))
    monkeypatch.setattr("mpk.search.save_last_results", lambda events: None)

    result = run_search(
        SearchQuery(),
        fetch_all=True,
        pause_seconds=0,
        on_page_fetched=lambda events, total: callbacks.append([event.id for event in events]),
    )

    assert [event.id for event in result.events] == ["a", "b", "c"]
    assert callbacks == [["a"], ["b"], ["c"]]


def test_pagination_repeated_page_raises_no_progress(monkeypatch) -> None:
    event = Event(id="a", url="https://example.test/a", title="A")

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def post(self, *args, **kwargs) -> httpx.Response:
            return httpx.Response(200, text="initial")

        def load_next_event(self) -> httpx.Response:
            return httpx.Response(200, text="repeat")

    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)
    monkeypatch.setattr("mpk.search.parse_total_count", lambda html: 2)
    monkeypatch.setattr("mpk.search.parse_search_results", lambda html: [event])
    monkeypatch.setattr("mpk.search.parse_next_event_fragment", lambda html: [event])

    with pytest.raises(RuntimeError, match="made no progress"):
        run_search(SearchQuery(), fetch_all=True, pause_seconds=0)


def test_pagination_has_bounded_safety_limit(monkeypatch) -> None:
    counter = 0

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def bootstrap(self) -> str:
            return ""

        def post(self, *args, **kwargs) -> httpx.Response:
            return httpx.Response(200, text="initial")

        def load_next_event(self) -> httpx.Response:
            return httpx.Response(200, text="next")

    def next_page(html: str) -> list[Event]:
        nonlocal counter
        counter += 1
        return [Event(id=str(counter), url=f"https://example.test/{counter}", title="Event")]

    monkeypatch.setattr("mpk.search.MpkClient", FakeClient)
    monkeypatch.setattr("mpk.search.MAX_PAGINATION_PAGES", 2)
    monkeypatch.setattr("mpk.search.parse_total_count", lambda html: 10)
    monkeypatch.setattr("mpk.search.parse_search_results", lambda html: [])
    monkeypatch.setattr("mpk.search.parse_next_event_fragment", next_page)

    with pytest.raises(RuntimeError, match="safety limit of 2 pages"):
        run_search(SearchQuery(), fetch_all=True, pause_seconds=0)


def test_client_pagination_raises_for_http_error(monkeypatch) -> None:
    from mpk.client import MpkClient

    def fail_get(path, **kwargs):
        request = httpx.Request("GET", f"https://example.test{path}")
        return httpx.Response(500, request=request)

    client = MpkClient()
    monkeypatch.setattr(client._client, "get", fail_get)
    try:
        import pytest

        with pytest.raises(httpx.HTTPStatusError):
            client.load_next_event()
    finally:
        client.close()
