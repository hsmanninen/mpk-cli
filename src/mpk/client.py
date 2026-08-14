"""HTTP client wrapping the MPK Koulutuskalenteri site."""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from . import __version__

BASE_URL = "https://koulutuskalenteri.mpk.fi"
DEFAULT_TIMEOUT = 20.0
USER_AGENT = f"mpk-cli/{__version__} (+https://github.com/hsmanninen/mpk-cli) python-httpx"


class MpkClient:
    """A thin wrapper around httpx.Client with the cookies/headers the site expects.

    Every instance is a fresh session; the server keeps search state per session,
    so isolating them per CLI invocation is deliberate.
    """

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        lang_id: int = 0,
        verbose: bool = False,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fi,en;q=0.7,sv;q=0.5",
            },
            follow_redirects=True,
            http2=False,
        )
        self._verbose = verbose
        self._bootstrapped = False
        self._lang_id = lang_id

    # ---- context manager ----------------------------------------------------

    def __enter__(self) -> MpkClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ---- low-level ----------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        r = self._client.get(path, **kwargs)
        r.raise_for_status()
        return r

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        r = self._client.post(path, **kwargs)
        r.raise_for_status()
        return r

    # ---- high-level ---------------------------------------------------------

    def bootstrap(self) -> str:
        """Fetch the calendar home page, priming cookies. Returns the HTML."""
        r = self.get("/Calendar/")
        html = r.text
        if self._lang_id != 0:
            # Switching language returns a fragment; ignore it, we only care
            # about the cookie side-effects.
            self.get(
                "/Calendar/ChangeLanguage",
                params={"languageId": self._lang_id},
            )
        self._bootstrapped = True
        return html

    def ensure_bootstrapped(self) -> None:
        if not self._bootstrapped:
            self.bootstrap()

    def load_next_event(self) -> httpx.Response:
        return self.get("/Calendar/LoadNextEvent")
