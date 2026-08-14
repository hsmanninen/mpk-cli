"""Coordination for synchronous network calls made by TUI workers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

from ..models import EventDetail

T = TypeVar("T")


class RequestCoordinator:
    """Serialize site access and reuse event details across TUI screens."""

    def __init__(self) -> None:
        self._request_lock = threading.Lock()
        self._details: dict[tuple[str, str], EventDetail] = {}

    def search(
        self,
        generation: int,
        is_current: Callable[[int], bool],
        request: Callable[[], T],
    ) -> T | None:
        """Run only a still-current search after earlier site access finishes."""
        with self._request_lock:
            if not is_current(generation):
                return None
            result = request()
            if not is_current(generation):
                return None
            return result

    def serialized(self, request: Callable[[], T]) -> T:
        """Run arbitrary site access without overlapping another request."""
        with self._request_lock:
            return request()

    def detail(
        self,
        event_id: str,
        lang: str,
        request: Callable[[], EventDetail],
    ) -> EventDetail:
        """Fetch one detail at a time, deduplicated by event and language."""
        key = (lang, event_id)
        with self._request_lock:
            cached = self._details.get(key)
            if cached is not None:
                return cached
            detail = request()
            self._details[key] = detail
            return detail
