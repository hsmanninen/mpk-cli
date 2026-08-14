"""Textual App entrypoint for the mpk TUI."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from ..config import Config, load_config, save_tui_theme
from ..models import FilterVocab
from ..vocab import VocabCache, get_vocab
from .screens.browse import ActiveFilters, BrowseScreen
from .screens.help import HelpScreen


class MpkApp(App):
    """Interactive TUI for MPK Koulutuskalenteri."""

    TITLE = "MPK · Koulutuskalenteri"
    SUB_TITLE = "koulutuskalenteri.mpk.fi"

    CSS_PATH = str(Path(__file__).parent / "theme.tcss")

    BINDINGS = [
        Binding("question_mark", "context_help", "Ohje", priority=True),
        Binding("f1", "context_help", "Ohje", show=False, priority=True),
        Binding("ctrl+q", "quit", "Lopeta", show=False, priority=True),
    ]

    SCREENS = {
        "help": HelpScreen,
    }

    def __init__(
        self,
        *,
        vocab: FilterVocab,
        cache: VocabCache,
        config: Config,
        initial_query: str = "",
        initial_filters: ActiveFilters | None = None,
        lang: str = "fi",
        begin: date | None = None,
        end: date | None = None,
        include_ongoing: bool = True,
    ) -> None:
        super().__init__()
        self._vocab = vocab
        self._cache = cache
        self._config = config
        self._initial_query = initial_query
        self._initial_filters = initial_filters or ActiveFilters.from_defaults(
            config.defaults.filters, vocab
        )
        self._lang = lang
        self._begin = begin
        self._end = end
        self._include_ongoing = include_ongoing
        self._persist_theme_changes = False

    def on_mount(self) -> None:
        self.push_screen(
            BrowseScreen(
                vocab=self._vocab,
                cache=self._cache,
                initial_query=self._initial_query,
                initial_filters=self._initial_filters,
                lang=self._lang,
                begin=self._begin,
                end=self._end,
                include_ongoing=self._include_ongoing,
                page_size=self._config.tui.page_size,
                show_registration_status=self._config.tui.show_registration_status,
                config=self._config,
            )
        )
        # Apply theme preference
        theme = self._config.tui.theme
        configured_theme = {"light": "textual-light", "dark": "textual-dark"}.get(theme, theme)
        if configured_theme != "auto" and configured_theme in self.available_themes:
            self.theme = configured_theme
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)
        self.call_after_refresh(self._enable_theme_persistence)

    def _enable_theme_persistence(self) -> None:
        self._persist_theme_changes = True

    def _on_theme_changed(self, theme) -> None:
        if not self._persist_theme_changes:
            return
        try:
            save_tui_theme(theme.name)
        except OSError as exc:
            self.notify(f"Teeman tallennus epäonnistui: {exc}", severity="warning")

    def action_context_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
            return
        screen_name = self.screen.__class__.__name__
        context = (
            "filters"
            if screen_name == "FilterScreen"
            else "detail"
            if screen_name == "DetailScreen"
            else "browse"
        )
        self.push_screen(HelpScreen(context=context))


def launch(
    *,
    initial_query: str = "",
    initial_filters: ActiveFilters | None = None,
    lang: str = "fi",
    begin: date | None = None,
    end: date | None = None,
    include_ongoing: bool = True,
    config: Config | None = None,
    vocab: FilterVocab | None = None,
    cache: VocabCache | None = None,
) -> None:
    """Build vocab, then run the TUI app."""
    config = config or load_config()
    if vocab is None or cache is None:
        vocab, cache = get_vocab(lang, config=config)
    app = MpkApp(
        vocab=vocab,
        cache=cache,
        config=config,
        initial_query=initial_query,
        initial_filters=initial_filters,
        lang=lang,
        begin=begin,
        end=end,
        include_ongoing=include_ongoing,
    )
    app.run()
