from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from mpk.config import Config, DefaultFiltersConfig, DefaultsConfig, TuiConfig
from mpk.models import Event, EventDetail, FilterOption, FilterVocab
from mpk.tui.app import MpkApp
from mpk.tui.requests import RequestCoordinator
from mpk.tui.screens.browse import ActiveFilters
from mpk.vocab import SCHEMA_VERSION, VocabCache


@pytest.fixture()
def vocab() -> FilterVocab:
    return FilterVocab(
        lang="fi",
        cities=[FilterOption("Helsinki", "Helsinki"), FilterOption("Tampere", "Tampere")],
        districts=[FilterOption("1000", "Etelä-Suomi")],
        specializations=[
            FilterOption("1002", "Ensiapu ja kenttälääkintä"),
            FilterOption("1042", "Kyberpuolustus"),
        ],
        target_groups=[FilterOption("1001", "Reserviläiset")],
        types=[FilterOption("12", "Koulutus")],
        implementation_modes=[
            FilterOption("1", "Verkkokoulutus"),
            FilterOption("1002", "Lähikoulutus"),
        ],
    )


@pytest.fixture()
def cache(vocab: FilterVocab) -> VocabCache:
    english = FilterVocab(
        lang="en",
        cities=[FilterOption("Helsinki", "Helsinki EN")],
        districts=vocab.districts,
        specializations=vocab.specializations,
        target_groups=vocab.target_groups,
        types=vocab.types,
        implementation_modes=vocab.implementation_modes,
    )
    return VocabCache(
        schema=SCHEMA_VERSION,
        fetched_at=datetime.now(UTC),
        source_hash="",
        languages={"fi": vocab, "en": english},
    )


@pytest.fixture(autouse=True)
def avoid_real_tui_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mpk.tui.screens.browse.save_last_results", lambda _events: None)


@pytest.fixture()
def stub_search(monkeypatch: pytest.MonkeyPatch):
    """Replace run_search with a callable stub. Captures the last SearchQuery."""

    calls: list = []

    def _run(query, **kw):
        from mpk.search import SearchResult

        calls.append(query)
        events = [
            Event(
                id=f"id{i}",
                url=f"https://x/e/{i}",
                title=f"Testikoulutus #{i}",
                start=datetime(2026, 9, 1 + i, 10, 0),
                end=datetime(2026, 9, 1 + i, 16, 0),
                city="Helsinki",
                registration_status="Julkaistu",
            )
            for i in range(3)
        ]
        return SearchResult(total=3, events=events, fetched=3)

    monkeypatch.setattr("mpk.tui.screens.browse.run_search", _run)
    return calls


@pytest.fixture()
def stub_detail(monkeypatch: pytest.MonkeyPatch):
    """Replace fetch_event_detail with a stub."""

    def _fetch(event_id, *, lang="fi", verbose=False):
        return EventDetail(
            id=event_id,
            url=f"https://x/e/{event_id}",
            title="Sotilaan taisteluensiavun peruskurssi",
            start=datetime(2026, 8, 22, 8, 0),
            end=datetime(2026, 8, 22, 18, 0),
            city="Tikkakoski",
            location="Tikkakoski / Vanha Esikuntakomppania",
            mode="Lähikoulutus",
            target_groups=["Reserviläiset"],
            description="Kurssin kuvaus.",
            goals="Kurssin tavoitteet.",
            target_group_note="Kaikille reserviläisille.",
            registration_url="https://ilmoittautuminen.mpk.fi/Registration/Login?id=1",
            registration_deadline="22.08.2026 08.00",
            raw_fields={"Keskeinen sisältö": "Ohjelma."},
        )

    monkeypatch.setattr("mpk.tui.screens.detail.fetch_event_detail", _fetch)
    monkeypatch.setattr("mpk.tui.screens.browse.fetch_event_detail", _fetch)


async def test_app_boots_and_runs_initial_search(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()
        # An initial search fired.
        assert len(stub_search) == 1
        assert app.focused is not None and app.focused.id == "search-input"


async def test_enter_query_and_submit_runs_search(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        stub_search.clear()

        await pilot.press("slash")
        await pilot.pause()
        for ch in "ensiapu":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert len(stub_search) == 1
        assert stub_search[0].text == "ensiapu"


async def test_searches_are_serialized_and_obsolete_queue_entries_are_skipped(
    vocab: FilterVocab,
    cache: VocabCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mpk.search import SearchResult

    calls: list[str] = []
    saved: list[list[str]] = []
    active = 0
    most_active = 0
    state_lock = threading.Lock()
    first_started = threading.Event()
    release_first = threading.Event()
    latest_finished = threading.Event()

    def blocking_search(query, **kwargs):
        nonlocal active, most_active
        text = query.text or "initial"
        with state_lock:
            calls.append(text)
            active += 1
            most_active = max(most_active, active)
        try:
            if text == "initial":
                first_started.set()
                assert release_first.wait(timeout=2)
            event = Event(id=text, url=f"https://x/{text}", title=text)
            return SearchResult(total=1, events=[event], fetched=1)
        finally:
            with state_lock:
                active -= 1
            if text == "latest":
                latest_finished.set()

    monkeypatch.setattr("mpk.tui.screens.browse.run_search", blocking_search)
    monkeypatch.setattr(
        "mpk.tui.screens.browse.save_last_results",
        lambda events: saved.append([event.id for event in events]),
    )
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        assert await asyncio.to_thread(first_started.wait, 1)
        search_input = app.screen.query_one("#search-input")
        search_input.value = "obsolete"
        app.screen.action_run_query()
        search_input.value = "latest"
        app.screen.action_run_query()
        release_first.set()
        assert await asyncio.to_thread(latest_finished.wait, 2)

        for _ in range(20):
            await pilot.pause()
            if app.screen._events and app.screen._events[0].id == "latest":
                break

        assert calls == ["initial", "latest"]
        assert most_active == 1
        assert app.screen._events[0].id == "latest"
        assert saved == [["latest"]]


async def test_search_does_not_automatically_fetch_event_details(
    vocab: FilterVocab,
    cache: VocabCache,
    stub_search,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "mpk.tui.screens.browse.fetch_event_detail",
        lambda event_id, **kwargs: calls.append(event_id),
    )
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        for _ in range(20):
            await pilot.pause()
            if app.screen._events:
                break
        await pilot.pause()
        assert calls == []


def test_detail_requests_are_deduplicated_while_in_flight() -> None:
    coordinator = RequestCoordinator()
    started = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    calls = 0
    detail = EventDetail(id="id", url="https://x/id", title="Title")

    def fetch() -> EventDetail:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return detail

    def fetch_again() -> EventDetail:
        second_entered.set()
        return coordinator.detail("id", "fi", fetch)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(coordinator.detail, "id", "fi", fetch)
        assert started.wait(timeout=1)
        second = pool.submit(fetch_again)
        assert second_entered.wait(timeout=1)
        release.set()
        assert first.result(timeout=1) is detail
        assert second.result(timeout=1) is detail

    assert calls == 1


async def test_help_screen_opens_and_closes(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        await pilot.press("question_mark")
        await pilot.pause()
        # We're now on the HelpScreen (topmost in the stack).
        from mpk.tui.screens.help import HelpScreen

        assert isinstance(app.screen, HelpScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)
        assert app.focused is not None and app.focused.id == "search-input"


async def test_wide_layout_loads_detail_in_preview_without_buttons(
    vocab: FilterVocab,
    cache: VocabCache,
    stub_search,
    stub_detail,
) -> None:
    from textual.widgets import Button, DataTable

    from mpk.tui.screens.browse import BrowseScreen
    from mpk.tui.widgets.event_preview import EventPreview

    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()
        assert isinstance(app.screen, BrowseScreen)

        app.screen.query_one("#results", DataTable).focus()
        await pilot.press("enter")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert isinstance(app.screen, BrowseScreen)
        assert not list(app.query(Button))
        assert app.focused is not None and app.focused.id == "results"
        preview = app.screen.query_one(EventPreview)
        assert app.screen._details["id0"].registration_url is not None
        assert "Sotilaan taisteluensiavun" in " ".join(
            str(widget.render()) for widget in preview.query(".preview-title")
        )


async def test_language_cycles(vocab: FilterVocab, cache: VocabCache, stub_search) -> None:
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        stub_search.clear()

        app.screen.query_one("#results").focus()
        await pilot.press("l")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        assert stub_search  # cycling triggers a re-search
        assert stub_search[-1].lang == "en"
        assert app.screen._vocab.lang == "en"


async def test_clear_filters_when_empty_is_noop(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        stub_search.clear()

        # Focus is likely on the DataTable — press 'x'.
        await pilot.press("x")
        await pilot.pause()

        # No filters were set, so no new search should have fired.
        assert len(stub_search) == 0


async def test_initial_filters_are_serialized(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    filters = ActiveFilters(
        cities=[FilterOption("Helsinki", "Helsinki")],
        specializations=[FilterOption("1002", "Ensiapu ja kenttälääkintä")],
    )
    app = MpkApp(
        vocab=vocab,
        cache=cache,
        config=Config(),
        initial_query="ensi",
        initial_filters=filters,
        lang="fi",
    )
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()

        assert stub_search
        q = stub_search[0]
        assert q.text == "ensi"
        assert q.cities == ["Helsinki"]
        assert q.specializations == ["1002"]


async def test_saved_default_filters_are_applied_at_tui_startup(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    config = Config(
        defaults=DefaultsConfig(filters=DefaultFiltersConfig(cities=["Helsinki"], modes=["1"]))
    )
    app = MpkApp(vocab=vocab, cache=cache, config=config)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        assert stub_search[0].cities == ["Helsinki"]
        assert stub_search[0].implementation_modes == ["1"]


async def test_tui_config_and_query_options_are_applied(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    from datetime import date

    from textual.widgets import DataTable

    config = Config(tui=TuiConfig(page_size=7, show_registration_status=False))
    app = MpkApp(
        vocab=vocab,
        cache=cache,
        config=config,
        begin=date(2027, 1, 2),
        end=date(2027, 1, 3),
        include_ongoing=False,
    )
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()

        query = stub_search[0]
        assert query.begin == date(2027, 1, 2)
        assert query.end == date(2027, 1, 3)
        assert query.include_ongoing is False
        table = app.screen.query_one("#results", DataTable)
        assert len(table.columns) == 5


def test_result_duration_and_status_formatting() -> None:
    from rich.text import Text

    from mpk.tui.screens.browse import _fmt_duration, _status_icon

    assert _fmt_duration(datetime(2026, 8, 12, 8), datetime(2026, 8, 12, 16)) == "8 h"
    assert _fmt_duration(datetime(2026, 8, 12), datetime(2026, 8, 14)) == "3 pv"
    assert _status_icon("Julkaistu (Ilmo auki 12.08.2026 saakka)") == Text("●", style="green")
    assert _status_icon("Ilmo kiinni") == Text("×", style="red")
    assert _status_icon("Täynnä") == Text("■", style="yellow")


def test_mode_icon_and_online_detection_use_vocab_ids(vocab: FilterVocab) -> None:
    from mpk.tui.screens.browse import _is_online, _mode_icon

    detail = EventDetail(
        id="id",
        url="https://example.test",
        title="Koulutus",
        mode="Verkkokoulutus",
    )

    assert _mode_icon(detail, vocab).plain == "◎"
    assert _is_online(detail, vocab)


async def test_results_use_compact_columns(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    from textual.widgets import DataTable

    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        table = app.screen.query_one("#results", DataTable)
        assert [str(column.label) for column in table.ordered_columns] == [
            "",
            "",
            "PVM",
            "Kesto",
            "Kaupunki",
            "Nimi",
        ]
        assert table.columns["city"].width == 14


async def test_online_detail_clears_result_duration(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    from textual.widgets import DataTable

    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        screen = app.screen
        screen._store_detail(
            "id0",
            EventDetail(
                id="id0",
                url="https://example.test",
                title="Verkkokoulutus",
                mode="Verkkokoulutus",
            ),
        )

        table = screen.query_one("#results", DataTable)
        assert table.get_cell("id0", "duration") == ""


async def test_palette_theme_change_is_persisted(
    vocab: FilterVocab,
    cache: VocabCache,
    stub_search,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[str] = []
    monkeypatch.setattr("mpk.tui.app.save_tui_theme", saved.append)
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        app._persist_theme_changes = True
        app.theme = "textual-light" if app.theme != "textual-light" else "textual-dark"
        await pilot.pause()
        assert saved[-1] == app.theme


async def test_unified_filter_screen_preserves_hidden_selection(
    vocab: FilterVocab,
) -> None:
    from textual.app import App
    from textual.widgets import SelectionList

    from mpk.tui.screens.filters import FilterScreen

    class PickerApp(App):
        def on_mount(self) -> None:
            self.push_screen(
                FilterScreen(
                    vocab=vocab,
                    selected={
                        "cities": [],
                        "districts": [],
                        "specializations": [],
                        "target_groups": [],
                        "modes": [],
                        "types": [],
                    },
                )
            )

    app = PickerApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        picker = app.screen
        selection = picker.query_one("#filter-options", SelectionList)
        selection.select("Helsinki")
        picker.query_one("#filter-query").value = "Tampere"
        await pilot.pause()
        picker.query_one("#filter-query").value = "Tamp"
        await pilot.pause()
        picker.query_one("#filter-query").value = ""
        await pilot.pause()
        assert "Helsinki" in selection.selected


async def test_filter_category_enter_opens_city_options(vocab: FilterVocab) -> None:
    from textual.app import App
    from textual.widgets import SelectionList

    from mpk.tui.screens.filters import FilterScreen

    class FilterApp(App):
        def on_mount(self) -> None:
            self.push_screen(
                FilterScreen(
                    vocab=vocab,
                    selected={
                        field: []
                        for field in (
                            "cities",
                            "districts",
                            "specializations",
                            "target_groups",
                            "modes",
                            "types",
                        )
                    },
                )
            )

    app = FilterApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.focused is not None and app.focused.id == "filter-categories"
        await pilot.press("enter")
        await pilot.pause()
        assert app.focused is not None and app.focused.id == "filter-options"
        options = app.screen.query_one("#filter-options", SelectionList)
        assert [option.value for option in options.options] == ["Helsinki", "Tampere"]
        await pilot.press("left")
        await pilot.pause()
        assert app.focused is not None and app.focused.id == "filter-categories"


async def test_filter_clear_all_resets_every_category(vocab: FilterVocab) -> None:
    from textual.app import App

    from mpk.tui.screens.filters import FilterScreen

    selected = {
        "cities": [vocab.cities[0]],
        "districts": [vocab.districts[0]],
        "specializations": [vocab.specializations[0]],
        "target_groups": [],
        "modes": [],
        "types": [],
    }

    class FilterApp(App):
        def on_mount(self) -> None:
            self.push_screen(FilterScreen(vocab=vocab, selected=selected))

    app = FilterApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+x")
        await pilot.pause()
        assert all(not values for values in app.screen._selected.values())


async def test_filter_screen_saves_and_resets_default(
    vocab: FilterVocab, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.app import App

    from mpk.tui.screens.filters import FilterScreen

    saved: list[dict[str, list[str]]] = []
    reset: list[bool] = []
    monkeypatch.setattr("mpk.tui.screens.filters.save_default_filters", saved.append)
    monkeypatch.setattr("mpk.tui.screens.filters.reset_default_filters", lambda: reset.append(True))
    config = Config()
    selected = {
        "cities": [vocab.cities[0]],
        "districts": [],
        "specializations": [],
        "target_groups": [],
        "modes": [],
        "types": [],
    }

    class FilterApp(App):
        def on_mount(self) -> None:
            self.push_screen(FilterScreen(vocab=vocab, selected=selected, config=config))

    app = FilterApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert saved[-1]["cities"] == ["Helsinki"]
        assert config.defaults.filters.cities == ["Helsinki"]

        await pilot.press("ctrl+r")
        await pilot.pause()
        assert reset == [True]
        assert not config.defaults.filters.any_set()


async def test_workspace_panes_show_focus_within(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    from textual.containers import Vertical
    from textual.widgets import DataTable

    from mpk.tui.widgets.event_preview import EventPreview

    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        results_pane = app.screen.query_one("#results-pane", Vertical)
        preview_pane = app.screen.query_one("#preview-pane", Vertical)

        app.screen.query_one("#results", DataTable).focus()
        await pilot.pause()
        assert results_pane.has_focus_within
        assert not preview_pane.has_focus_within

        app.screen.query_one(EventPreview).focus()
        await pilot.pause()
        assert preview_pane.has_focus_within
        assert not results_pane.has_focus_within


async def test_preview_metadata_uses_wrapping_value_column() -> None:
    from textual.app import App, ComposeResult

    from mpk.tui.widgets.event_preview import EventPreview

    detail = EventDetail(
        id="id",
        url="https://example.test",
        title="Long metadata",
        location="A very long location that must wrap beneath the value rather than the label",
        contact="Long contact information with several words and details",
    )

    class PreviewApp(App):
        CSS_PATH = MpkApp.CSS_PATH

        def compose(self) -> ComposeResult:
            yield EventPreview()

        def on_mount(self) -> None:
            self.query_one(EventPreview).show_detail(detail)

    app = PreviewApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        preview = app.query_one(EventPreview)
        labels = list(preview.query(".metadata-label"))
        values = list(preview.query(".metadata-value"))
        assert len(labels) == len(values) == 2
        assert labels[0].region.x < values[0].region.x
        assert values[0].region.width > labels[0].region.width


async def test_status_bar_has_visible_busy_state() -> None:
    from textual.app import App, ComposeResult

    from mpk.tui.widgets.status_bar import StatusBar

    class StatusApp(App):
        def compose(self) -> ComposeResult:
            yield StatusBar()

    app = StatusApp()
    async with app.run_test(size=(80, 10)) as pilot:
        status = app.query_one(StatusBar)
        status.busy = True
        await pilot.pause()
        assert status.has_class("busy")
        spinner = str(status.query_one("#status-spinner").render())
        assert any(frame in spinner for frame in status._SPINNER)
        assert str(status.query_one("#status-message").render()) == ""
        spinner_width = status.query_one("#status-spinner").region.width

        status.busy = False
        await pilot.pause()
        assert not status.has_class("busy")
        assert status.query_one("#status-spinner").region.width == spinner_width


async def test_status_bar_is_not_covered_by_footer(
    vocab: FilterVocab, cache: VocabCache, stub_search
) -> None:
    from textual.widgets import Footer

    from mpk.tui.widgets.status_bar import StatusBar

    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        status = app.screen.query_one(StatusBar)
        footer = app.screen.query_one(Footer)
        assert status.region.y + status.region.height <= footer.region.y


async def test_compact_layout_opens_full_width_detail(
    vocab: FilterVocab, cache: VocabCache, stub_search, stub_detail
) -> None:
    from textual.widgets import DataTable

    from mpk.tui.screens.detail import DetailScreen

    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        app.screen.query_one("#results", DataTable).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)


async def test_cursor_navigation_updates_summary_without_fetching_detail(
    vocab: FilterVocab, cache: VocabCache, stub_search, monkeypatch: pytest.MonkeyPatch
) -> None:
    from textual.widgets import DataTable

    calls: list[str] = []
    monkeypatch.setattr(
        "mpk.tui.screens.browse.fetch_event_detail",
        lambda event_id, **kwargs: calls.append(event_id),
    )
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        table = app.screen.query_one("#results", DataTable)
        table.focus()
        await pilot.press("down")
        await pilot.pause()
        assert app.screen._selected_event_id == "id1"
        assert calls == []


async def test_registration_action_uses_loaded_detail(
    vocab: FilterVocab,
    cache: VocabCache,
    stub_search,
    stub_detail,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.widgets import DataTable

    opened: list[str] = []
    monkeypatch.setattr("mpk.tui.screens.browse.webbrowser.open", opened.append)
    app = MpkApp(vocab=vocab, cache=cache, config=Config())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        app.screen.query_one("#results", DataTable).focus()
        await pilot.press("enter")
        await asyncio.sleep(0.2)
        await pilot.pause()
        await pilot.press("i")
        assert opened == ["https://ilmoittautuminen.mpk.fi/Registration/Login?id=1"]
