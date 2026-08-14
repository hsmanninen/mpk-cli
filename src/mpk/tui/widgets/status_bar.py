"""Status bar widget: count, activity spinner, transient messages."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Horizontal):
    """Bottom status bar with count, spinner, and a rolling message area."""

    count = reactive("")
    spinner_frame = reactive(0)
    busy = reactive(False)
    message = reactive("")

    _SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        super().__init__()
        self._count = Static("", id="status-count")
        self._msg = Static("", id="status-message")
        self._spin = Static("", id="status-spinner")
        self._clear_timer = None

    def compose(self):
        yield self._spin
        yield self._count
        yield self._msg

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if self.busy:
            self.spinner_frame = (self.spinner_frame + 1) % len(self._SPINNER)
            self._render_spinner()
        else:
            self._render_spinner()

    def watch_busy(self, busy: bool) -> None:
        """Make network activity visible beyond the animated glyph."""
        self.set_class(busy, "busy")
        self._render_spinner()

    def watch_count(self, val: str) -> None:
        self._count.update(val)

    def watch_message(self, val: str) -> None:
        self._msg.update(val)

    def _render_spinner(self) -> None:
        """Render activity in a fixed leading slot to keep content stable."""
        if self.busy:
            self._spin.update(self._SPINNER[self.spinner_frame])
        else:
            self._spin.update(" ")

    def notify_transient(self, text: str) -> None:
        """Show `text` for a few seconds, then clear."""
        self.message = text
        if self._clear_timer is not None:
            self._clear_timer.stop()
        self._clear_timer = self.set_timer(4.0, lambda: setattr(self, "message", ""))
