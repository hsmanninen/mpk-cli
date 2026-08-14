"""Unified keyboard-first filter screen."""

from __future__ import annotations

from copy import deepcopy

from rapidfuzz import fuzz, process
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, OptionList, SelectionList, Static

from ...config import Config, DefaultFiltersConfig, reset_default_filters, save_default_filters
from ...models import FilterOption, FilterVocab

CATEGORIES = (
    ("cities", "Kaupungit", "cities"),
    ("districts", "Piirit", "districts"),
    ("specializations", "Aiheet", "specializations"),
    ("target_groups", "Kohderyhmät", "target_groups"),
    ("modes", "Koulutusmuodot", "implementation_modes"),
    ("types", "Tapahtumatyypit", "types"),
)


class FilterQuery(Input):
    BINDINGS = [
        Binding("question_mark", "app.context_help", "Ohje", show=False, priority=True),
        Binding("f1", "app.context_help", "Ohje", show=False, priority=True),
    ]


class CategoryList(OptionList):
    BINDINGS = [
        Binding("enter,right", "open_category", "Avaa", show=False),
    ]

    def action_open_category(self) -> None:
        self.screen.action_focus_options()


class FilterOptions(SelectionList[str]):
    BINDINGS = [
        Binding("left", "focus_categories", "Kategoriat", show=False),
        Binding("slash", "focus_query", "Hae", show=False),
    ]

    def action_focus_categories(self) -> None:
        self.screen.action_focus_categories()

    def action_focus_query(self) -> None:
        self.screen.action_focus_query()


class FilterScreen(ModalScreen[dict[str, list[FilterOption]] | None]):
    """Edit all filter dimensions as one staged operation."""

    BINDINGS = [
        Binding("escape", "cancel", "Peruuta"),
        Binding("ctrl+enter", "apply", "Käytä", priority=True),
        Binding("ctrl+x", "clear_all", "Tyhjennä kaikki", priority=True),
        Binding("ctrl+s", "save_default", "Tallenna oletus", priority=True),
        Binding("ctrl+r", "reset_default", "Poista oletus", priority=True),
        Binding("tab", "focus_next", "Seuraava", show=False),
        Binding("shift+tab", "focus_previous", "Edellinen", show=False),
    ]

    def __init__(
        self,
        *,
        vocab: FilterVocab,
        selected: dict[str, list[FilterOption]],
        config: Config | None = None,
    ) -> None:
        super().__init__()
        self._vocab = vocab
        self._selected = deepcopy(selected)
        self._category = CATEGORIES[0][0]
        self._config = config or Config()
        self._has_saved_default = self._config.defaults.filters.any_set()

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-body"):
            yield Static("SUODATTIMET", classes="eyebrow", markup=False)
            yield Static(
                "Valitse kategoria nuolilla ja avaa vaihtoehdot Enterillä tai oikealla nuolella.",
                id="filter-intro",
                markup=False,
            )
            with Horizontal(id="filter-workspace"):
                yield CategoryList(*[label for _, label, _ in CATEGORIES], id="filter-categories")
                with Vertical(id="filter-options-pane"):
                    yield Static("Kaupungit", id="filter-options-title", markup=False)
                    yield FilterQuery(placeholder="Rajaa vaihtoehtoja", id="filter-query")
                    yield FilterOptions(id="filter-options")
            yield Static("", id="filter-summary", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        categories = self.query_one("#filter-categories", OptionList)
        categories.highlighted = 0
        categories.focus()
        self._rebuild()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 90 or event.size.height < 26, "compact")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id != "filter-categories":
            return
        self._capture_visible_selection()
        self._category = CATEGORIES[event.option_index][0]
        self.query_one("#filter-options-title", Static).update(CATEGORIES[event.option_index][1])
        self.query_one("#filter-query", Input).value = ""
        self._rebuild()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-query":
            self._rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-query":
            self.query_one("#filter-options", SelectionList).focus()

    def _options_for_category(self) -> list[FilterOption]:
        _, _, vocab_field = next(item for item in CATEGORIES if item[0] == self._category)
        return list(getattr(self._vocab, vocab_field))

    def _capture_visible_selection(self) -> None:
        selection = self.query_one("#filter-options", SelectionList)
        if not selection.options:
            return
        selected_values = {option.value for option in self._selected[self._category]}
        visible_values = {option.value for option in selection.options}
        selected_values -= visible_values
        selected_values |= set(selection.selected)
        by_value = {option.value: option for option in self._options_for_category()}
        self._selected[self._category] = [
            by_value[value] for value in by_value if value in selected_values
        ]

    def _rebuild(self) -> None:
        selection = self.query_one("#filter-options", SelectionList)
        self._capture_visible_selection()
        query = self.query_one("#filter-query", Input).value.strip()
        options = self._options_for_category()
        if query:
            labels = {option.label: option for option in options}
            ranked = process.extract(query, labels.keys(), scorer=fuzz.WRatio, limit=len(labels))
            options = [labels[label] for label, score, _ in ranked if score >= 35]
        selected_values = {option.value for option in self._selected[self._category]}
        selection.clear_options()
        for option in options:
            selection.add_option((option.label, option.value, option.value in selected_values))
        count = sum(len(values) for values in self._selected.values())
        default_state = (
            "oletus tallennettu" if self._has_saved_default else "ei tallennettua oletusta"
        )
        self.query_one("#filter-summary", Static).update(
            f"{count} valittu · {default_state}   Space valitse   Ctrl+X tyhjennä   Ctrl+S tallenna oletus   Ctrl+R poista oletus   Ctrl+Enter käytä"
        )

    def action_focus_options(self) -> None:
        options = self.query_one("#filter-options", FilterOptions)
        options.focus()
        if options.highlighted is None and options.options:
            options.highlighted = 0

    def action_focus_categories(self) -> None:
        self.query_one("#filter-categories", CategoryList).focus()

    def action_focus_query(self) -> None:
        query = self.query_one("#filter-query", FilterQuery)
        query.focus()
        query.select_all()

    def action_clear_all(self) -> None:
        self.query_one("#filter-options", SelectionList).deselect_all()
        for field_name in self._selected:
            self._selected[field_name] = []
        self._rebuild()

    def action_save_default(self) -> None:
        self._capture_visible_selection()
        values = {
            field_name: [option.value for option in options]
            for field_name, options in self._selected.items()
        }
        try:
            save_default_filters(values)
        except OSError as exc:
            self.notify(f"Oletussuodattimien tallennus epäonnistui: {exc}", severity="error")
            return
        self._config.defaults.filters = DefaultFiltersConfig(**values)
        self._has_saved_default = self._config.defaults.filters.any_set()
        self._rebuild()
        self.notify("Oletussuodattimet tallennettu.", severity="information")

    def action_reset_default(self) -> None:
        try:
            reset_default_filters()
        except OSError as exc:
            self.notify(f"Oletussuodattimien poisto epäonnistui: {exc}", severity="error")
            return
        self._has_saved_default = False
        self._config.defaults.filters = DefaultFiltersConfig()
        self._rebuild()
        self.notify("Tallennettu oletussuodatin poistettu.", severity="information")

    def action_apply(self) -> None:
        self._capture_visible_selection()
        self.dismiss(self._selected)

    def action_cancel(self) -> None:
        self.dismiss(None)
