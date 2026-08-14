"""Responsive results workspace for the MPK TUI."""

from __future__ import annotations

import contextlib
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from ...config import Config, DefaultFiltersConfig
from ...history import save as save_last_results
from ...models import Event, EventDetail, FilterOption, FilterVocab
from ...search import SearchQuery, fetch_event_detail, run_search
from ...vocab import VocabCache, get_vocab, is_stale
from ..clipboard import copy as copy_to_clipboard
from ..requests import RequestCoordinator
from ..widgets.event_preview import EventPreview
from ..widgets.filter_chips import FilterChips
from ..widgets.status_bar import StatusBar
from .detail import DetailScreen
from .filters import FilterScreen

LANG_CYCLE = ["fi", "en", "sv"]


@dataclass
class ActiveFilters:
    cities: list[FilterOption] = field(default_factory=list)
    districts: list[FilterOption] = field(default_factory=list)
    specializations: list[FilterOption] = field(default_factory=list)
    target_groups: list[FilterOption] = field(default_factory=list)
    modes: list[FilterOption] = field(default_factory=list)
    types: list[FilterOption] = field(default_factory=list)

    def clear(self) -> None:
        for values in (
            self.cities,
            self.districts,
            self.specializations,
            self.target_groups,
            self.modes,
            self.types,
        ):
            values.clear()

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

    def as_mapping(self) -> dict[str, list[FilterOption]]:
        return {
            "cities": list(self.cities),
            "districts": list(self.districts),
            "specializations": list(self.specializations),
            "target_groups": list(self.target_groups),
            "modes": list(self.modes),
            "types": list(self.types),
        }

    @classmethod
    def from_defaults(cls, defaults: DefaultFiltersConfig, vocab: FilterVocab) -> ActiveFilters:
        def selected(vocab_field: str, values: list[str]) -> list[FilterOption]:
            wanted = set(values)
            return [option for option in getattr(vocab, vocab_field) if option.value in wanted]

        return cls(
            cities=selected("cities", defaults.cities),
            districts=selected("districts", defaults.districts),
            specializations=selected("specializations", defaults.specializations),
            target_groups=selected("target_groups", defaults.target_groups),
            modes=selected("implementation_modes", defaults.modes),
            types=selected("types", defaults.types),
        )


def _fmt_date(value: datetime | None) -> str:
    return value.strftime("%d.%m.%y") if value else ""


def _fmt_duration(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return ""
    if start.date() == end.date() and (start.hour or start.minute or end.hour or end.minute):
        minutes = max(0, int((end - start).total_seconds() // 60))
        hours, remainder = divmod(minutes, 60)
        return f"{hours} h" if remainder == 0 else f"{hours} h {remainder} min"
    return f"{(end.date() - start.date()).days + 1} pv"


def _status_icon(status: str | None) -> Text:
    normalized = (status or "").casefold()
    if "täynnä" in normalized or "full" in normalized or "fullbok" in normalized:
        return Text("■", style="yellow")
    if "ilmo kiinni" in normalized or "registration closed" in normalized:
        return Text("×", style="red")
    if "ilmo auki" in normalized or "registration open" in normalized:
        return Text("●", style="green")
    return Text("·", style="dim")


_MODE_ICONS: dict[str, tuple[str, str]] = {
    "1002": ("▣", "cyan"),
    "1": ("◎", "magenta"),
    "1003": ("◐", "yellow"),
}


def _mode_icon(detail: EventDetail, vocab: FilterVocab) -> Text:
    mode_values = {option.label.casefold(): option.value for option in vocab.implementation_modes}
    mode_value = mode_values.get((detail.mode or "").casefold())
    mode_symbol, mode_style = _MODE_ICONS.get(mode_value or "", ("·", "dim"))
    return Text(mode_symbol, style=mode_style)


def _is_online(detail: EventDetail, vocab: FilterVocab) -> bool:
    online_labels = {
        option.label.casefold() for option in vocab.implementation_modes if option.value == "1"
    }
    return (detail.mode or "").casefold() in online_labels


class SearchInput(Input):
    """Search input that keeps global discovery keys available while editing."""

    BINDINGS = [
        Binding("question_mark", "app.context_help", "Ohje", show=False, priority=True),
        Binding("f1", "app.context_help", "Ohje", show=False, priority=True),
    ]


class BrowseScreen(Screen):
    """Search results and an explicit-load event preview."""

    BINDINGS = [
        Binding("slash", "focus_search", "Hae", priority=True),
        Binding("f", "filters", "Suodattimet"),
        Binding("r", "run_query", "Päivitä"),
        Binding("l", "cycle_lang", "Kieli"),
        Binding("o", "open_current", "Avaa"),
        Binding("i", "open_registration", "Ilmoittaudu", show=False),
        Binding("y", "yank_current", "Kopioi", show=False),
        Binding("x", "clear_filters", "Tyhjennä", show=False),
        Binding("question_mark", "show_help", "Ohje", priority=True),
        Binding("f1", "show_help", "Ohje", show=False, priority=True),
        Binding("escape", "escape", "Takaisin", show=False),
        Binding("q", "app.quit", "Lopeta"),
        Binding("ctrl+q", "app.quit", "Lopeta", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        vocab: FilterVocab,
        cache: VocabCache,
        initial_query: str = "",
        initial_filters: ActiveFilters | None = None,
        lang: str = "fi",
        begin: date | None = None,
        end: date | None = None,
        include_ongoing: bool = True,
        page_size: int = 50,
        show_registration_status: bool = True,
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self._vocab = vocab
        self._cache = cache
        self._config = config or Config()
        self._lang = lang
        self._initial_query = initial_query
        self._filters = initial_filters or ActiveFilters()
        self._begin = begin
        self._end = end
        self._include_ongoing = include_ongoing
        self._page_size = page_size
        self._show_registration_status = show_registration_status
        self._events: list[Event] = []
        self._events_by_id: dict[str, Event] = {}
        self._details: dict[str, EventDetail] = {}
        self._selected_event_id: str | None = None
        self._search_generation = 0
        self._detail_generation = 0
        self._language_generation = 0
        self._compact = False
        self._requests = RequestCoordinator()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="browse-header"):
            with Horizontal(id="search-row"):
                yield Static("HAKU", classes="eyebrow", markup=False)
                yield SearchInput(
                    placeholder="Hae koulutuksia",
                    id="search-input",
                    value=self._initial_query,
                )
                yield Static(self._lang.upper(), id="lang-indicator", markup=False)
            yield FilterChips()
        with Horizontal(id="workspace"):
            with Vertical(id="results-pane", classes="pane"):
                yield Static("TULOKSET", classes="pane-title", markup=False)
                yield DataTable(id="results", cursor_type="row", zebra_stripes=False)
            with Vertical(id="preview-pane", classes="pane"):
                yield EventPreview(id="event-preview")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        if self._show_registration_status:
            table.add_column("", width=1, key="status")
        table.add_column("", width=1, key="mode")
        table.add_column("PVM", width=8, key="date")
        table.add_column("Kesto", width=11, key="duration")
        table.add_column("Kaupunki", width=14, key="city")
        table.add_column("Nimi", key="title")
        self.query_one(EventPreview).show_empty()
        self._refresh_chips()
        self.query_one("#search-input", Input).focus()
        self._set_compact(self.size.width < 100)
        self.action_run_query()

    def on_resize(self, event: events.Resize) -> None:
        self._set_compact(event.size.width < 100)

    def _set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.set_class(compact, "compact")

    def _refresh_chips(self) -> None:
        self.query_one(FilterChips).update_filters(**self._filters.as_mapping())

    def action_filters(self) -> None:
        focused = self.focused

        def apply(result: dict[str, list[FilterOption]] | None) -> None:
            if result is not None:
                for field_name, options in result.items():
                    setattr(self._filters, field_name, options)
                self._refresh_chips()
                self.action_run_query()
            if focused is not None and focused.is_mounted:
                focused.focus()

        self.app.push_screen(
            FilterScreen(
                vocab=self._vocab,
                selected=self._filters.as_mapping(),
                config=self._config,
            ),
            apply,
        )

    def action_clear_filters(self) -> None:
        if self._filters.any_set():
            self._filters.clear()
            self._refresh_chips()
            self.action_run_query()

    def action_focus_search(self) -> None:
        search = self.query_one("#search-input", Input)
        search.focus()
        search.select_all()

    def action_escape(self) -> None:
        if isinstance(self.focused, Input):
            self.query_one("#results", DataTable).focus()

    def action_show_help(self) -> None:
        focused = self.focused

        def restore(_: object = None) -> None:
            if focused is not None and focused.is_mounted:
                focused.focus()

        from .help import HelpScreen

        self.app.push_screen(HelpScreen(context="browse"), restore)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self.action_run_query()
            self.query_one("#results", DataTable).focus()

    def action_run_query(self) -> None:
        query = SearchQuery(
            text=self.query_one("#search-input", Input).value.strip() or None,
            begin=self._begin,
            end=self._end,
            include_ongoing=self._include_ongoing,
            lang=self._lang,
            cities=[option.value for option in self._filters.cities],
            districts=[option.value for option in self._filters.districts],
            specializations=[option.value for option in self._filters.specializations],
            target_groups=[option.value for option in self._filters.target_groups],
            types=[option.value for option in self._filters.types],
            implementation_modes=[option.value for option in self._filters.modes],
        )
        status = self.query_one(StatusBar)
        status.busy = True
        status.message = ""
        self._search_generation += 1
        self.run_worker(
            self._search_worker(query, self._search_generation),
            group="search",
            thread=True,
            exit_on_error=False,
        )

    async def _search_worker(self, query: SearchQuery, generation: int) -> None:
        try:
            result = self._requests.search(
                generation,
                lambda candidate: candidate == self._search_generation,
                lambda: run_search(query, limit=self._page_size, persist_history=False),
            )
        except Exception as exc:
            self.app.call_from_thread(self._on_search_error, generation, str(exc))
            return
        if result is None:
            return
        self.app.call_from_thread(self._on_search_done, generation, result.events, result.total)

    def _on_search_error(self, generation: int, message: str) -> None:
        if generation != self._search_generation or not self.is_mounted:
            return
        status = self.query_one(StatusBar)
        status.busy = False
        status.message = f"Haku epäonnistui. Edelliset tulokset säilytettiin: {message}"

    def _on_search_done(self, generation: int, events: list[Event], total: int | None) -> None:
        if generation != self._search_generation or not self.is_mounted:
            return
        self._events = events
        self._events_by_id = {event.id: event for event in events}
        self._details.clear()
        with contextlib.suppress(OSError):
            save_last_results(events)
        table = self.query_one("#results", DataTable)
        table.clear()
        for event in events:
            row: list[object] = [
                Text("·", style="dim"),
                _fmt_date(event.start),
                _fmt_duration(event.start, event.end),
                event.city or "",
                event.title,
            ]
            if self._show_registration_status:
                row.insert(0, _status_icon(event.registration_status))
            table.add_row(*row, key=event.id)
        status = self.query_one(StatusBar)
        status.busy = False
        status.count = f"{len(events)} / {total}" if total is not None else str(len(events))
        status.message = "Valitse tapahtuma" if events else "Ei tuloksia"
        if events:
            self._selected_event_id = events[0].id
            self.query_one(EventPreview).show_summary(events[0])
        else:
            self._selected_event_id = None
            self.query_one(EventPreview).show_empty()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event_id = str(event.row_key.value)
        selected = self._events_by_id.get(event_id)
        if selected is None:
            return
        self._selected_event_id = event_id
        preview = self.query_one(EventPreview)
        detail = self._details.get(event_id)
        if detail is not None:
            preview.show_detail(detail)
        else:
            preview.show_summary(selected)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        selected = self._current_event()
        if selected is None:
            return
        if self._compact:
            self.app.push_screen(
                DetailScreen(event=selected, lang=self._lang, requests=self._requests)
            )
        else:
            self._load_detail(selected)

    def _load_detail(self, event: Event) -> None:
        cached = self._details.get(event.id)
        if cached is not None:
            self.query_one(EventPreview).show_detail(cached)
            return
        self._detail_generation += 1
        generation = self._detail_generation
        lang = self._lang
        self.query_one(EventPreview).show_loading(event)
        self.run_worker(
            self._detail_worker(event, generation, lang),
            group="detail",
            exclusive=True,
            thread=True,
        )

    async def _detail_worker(self, event: Event, generation: int, lang: str) -> None:
        try:
            detail = self._requests.detail(
                event.id,
                lang,
                lambda: fetch_event_detail(event.id, lang=lang),
            )
        except Exception as exc:
            self.app.call_from_thread(self._on_detail_error, event, generation, str(exc))
            return
        self.app.call_from_thread(self._on_detail_loaded, event.id, generation, detail)

    def _on_detail_error(self, event: Event, generation: int, message: str) -> None:
        if generation == self._detail_generation and self.is_mounted:
            self.query_one(EventPreview).show_error(event, message)

    def _on_detail_loaded(self, event_id: str, generation: int, detail: EventDetail) -> None:
        if generation != self._detail_generation or not self.is_mounted:
            return
        self._store_detail(event_id, detail)
        if event_id == self._selected_event_id:
            self.query_one(EventPreview).show_detail(detail)

    def _store_detail(self, event_id: str, detail: EventDetail) -> None:
        self._details[event_id] = detail
        if event_id not in self._events_by_id:
            return
        table = self.query_one("#results", DataTable)
        table.update_cell(event_id, "mode", _mode_icon(detail, self._vocab), update_width=False)
        if _is_online(detail, self._vocab):
            table.update_cell(event_id, "duration", "", update_width=False)

    def _current_event(self) -> Event | None:
        return self._events_by_id.get(self._selected_event_id or "")

    def action_open_current(self) -> None:
        event = self._current_event()
        if event is not None:
            webbrowser.open(event.url)

    def action_yank_current(self) -> None:
        event = self._current_event()
        if event is not None:
            self.notify(copy_to_clipboard(event.url), severity="information")

    def action_open_registration(self) -> None:
        detail = self._details.get(self._selected_event_id or "")
        if detail and detail.registration_url:
            webbrowser.open(detail.registration_url)
        else:
            self.notify("Lataa ensin tapahtuman tiedot Enterillä.", severity="warning")

    def action_cycle_lang(self) -> None:
        index = LANG_CYCLE.index(self._lang) if self._lang in LANG_CYCLE else 0
        target = LANG_CYCLE[(index + 1) % len(LANG_CYCLE)]
        self._language_generation += 1
        generation = self._language_generation
        status = self.query_one(StatusBar)
        status.busy = True
        status.message = ""
        self.run_worker(self._load_language(target, generation), exclusive=True, thread=True)

    async def _load_language(self, lang: str, generation: int) -> None:
        try:
            vocab = self._cache.languages.get(lang)
            if vocab is None or is_stale(self._cache, lang, self._config.cache.filters_ttl_days):
                vocab, cache = self._requests.serialized(
                    lambda: get_vocab(lang, config=self._config)
                )
            else:
                cache = self._cache
        except Exception as exc:
            self.app.call_from_thread(self._on_language_error, generation, str(exc))
            return
        self.app.call_from_thread(self._on_language_loaded, generation, lang, vocab, cache)

    def _on_language_error(self, generation: int, message: str) -> None:
        if generation == self._language_generation and self.is_mounted:
            status = self.query_one(StatusBar)
            status.busy = False
            status.message = f"Kielen vaihto epäonnistui: {message}"

    def _on_language_loaded(
        self,
        generation: int,
        lang: str,
        vocab: FilterVocab,
        cache: VocabCache,
    ) -> None:
        if generation != self._language_generation or not self.is_mounted:
            return
        self._lang = lang
        self._vocab = vocab
        self._cache = cache
        for active_field, vocab_field in (
            ("cities", "cities"),
            ("districts", "districts"),
            ("specializations", "specializations"),
            ("target_groups", "target_groups"),
            ("modes", "implementation_modes"),
            ("types", "types"),
        ):
            values = {option.value for option in getattr(self._filters, active_field)}
            setattr(
                self._filters,
                active_field,
                [option for option in getattr(vocab, vocab_field) if option.value in values],
            )
        self._details.clear()
        self.query_one("#lang-indicator", Static).update(lang.upper())
        self._refresh_chips()
        self.action_run_query()
