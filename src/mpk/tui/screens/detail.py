"""Full-width event detail screen used by compact layouts."""

from __future__ import annotations

import webbrowser

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header

from ...models import Event, EventDetail
from ...search import fetch_event_detail
from ..clipboard import copy as copy_to_clipboard
from ..requests import RequestCoordinator
from ..widgets.event_preview import EventPreview


class DetailScreen(Screen):
    BINDINGS = [
        ("escape,backspace", "app.pop_screen", "Takaisin"),
        ("o", "open_browser", "Avaa"),
        ("i", "open_registration", "Ilmoittaudu"),
        ("y", "yank_url", "Kopioi"),
        Binding("enter", "retry", "Yritä uudelleen", show=False),
        ("question_mark,f1", "app.context_help", "Ohje"),
    ]

    def __init__(
        self,
        *,
        event: Event,
        lang: str = "fi",
        requests: RequestCoordinator | None = None,
    ) -> None:
        super().__init__()
        self._event = event
        self._lang = lang
        self._detail: EventDetail | None = None
        self._generation = 0
        self._requests = requests or RequestCoordinator()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield EventPreview(id="detail-preview")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Tapahtuman tiedot"
        self.action_retry()

    def action_retry(self) -> None:
        self._generation += 1
        generation = self._generation
        self.query_one(EventPreview).show_loading(self._event)
        self.run_worker(self._load(generation), exclusive=True, thread=True)

    async def _load(self, generation: int) -> None:
        try:
            detail = self._requests.detail(
                self._event.id,
                self._lang,
                lambda: fetch_event_detail(self._event.id, lang=self._lang),
            )
        except Exception as exc:
            self.app.call_from_thread(self._on_error, generation, str(exc))
            return
        self.app.call_from_thread(self._on_loaded, generation, detail)

    def _on_error(self, generation: int, message: str) -> None:
        if generation == self._generation and self.is_mounted:
            self.query_one(EventPreview).show_error(self._event, message)

    def _on_loaded(self, generation: int, detail: EventDetail) -> None:
        if generation != self._generation or not self.is_mounted:
            return
        self._detail = detail
        self.query_one(EventPreview).show_detail(detail)

    def action_open_browser(self) -> None:
        webbrowser.open(self._event.url)

    def action_yank_url(self) -> None:
        self.notify(copy_to_clipboard(self._event.url), severity="information")

    def action_open_registration(self) -> None:
        if self._detail and self._detail.registration_url:
            webbrowser.open(self._detail.registration_url)
        else:
            self.notify("Ei ilmoittautumislinkkiä.", severity="warning")
