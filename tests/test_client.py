from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import mpk.client as client_module
from mpk import __version__
from mpk.client import MpkClient

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], MpkClient]:
    real_client = httpx.Client

    def build(handler: Handler, **kwargs: object) -> MpkClient:
        transport = httpx.MockTransport(handler)

        def client_factory(**client_kwargs: object) -> httpx.Client:
            return real_client(**client_kwargs, transport=transport)

        monkeypatch.setattr(client_module.httpx, "Client", client_factory)
        return MpkClient(**kwargs)

    return build


def test_requests_include_identifying_headers(
    mock_client: Callable[[Handler], MpkClient],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://calendar.example/Calendar/"
        assert request.headers["user-agent"] == (
            f"mpk-cli/{__version__} (+https://github.com/hsmanninen/mpk-cli) python-httpx"
        )
        assert request.headers["accept"] == (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        assert request.headers["accept-language"] == "fi,en;q=0.7,sv;q=0.5"
        return httpx.Response(200, text="home")

    with mock_client(handler, base_url="https://calendar.example") as client:
        assert client.bootstrap() == "home"


def test_bootstrap_persists_session_cookies_and_runs_only_once(
    mock_client: Callable[[Handler], MpkClient],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/Calendar/":
            return httpx.Response(
                200,
                text="home",
                headers=[
                    ("set-cookie", "ASP.NET_SessionId=session-123; Path=/; HttpOnly"),
                    ("set-cookie", "CalendarLanguageCookie=0; Path=/"),
                    ("set-cookie", "LocaleCookie=fi-FI; Path=/"),
                ],
            )
        assert request.headers["cookie"] == (
            "ASP.NET_SessionId=session-123; CalendarLanguageCookie=0; LocaleCookie=fi-FI"
        )
        return httpx.Response(200, text='{"Empty":1}')

    with mock_client(handler) as client:
        client.ensure_bootstrapped()
        client.ensure_bootstrapped()
        assert client.load_next_event().text == '{"Empty":1}'

    assert [request.url.path for request in requests] == [
        "/Calendar/",
        "/Calendar/LoadNextEvent",
    ]


def test_new_clients_do_not_share_session_cookies(
    mock_client: Callable[[Handler], MpkClient],
) -> None:
    home_cookies: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        home_cookies.append(request.headers.get("cookie"))
        return httpx.Response(
            200,
            headers={"set-cookie": "ASP.NET_SessionId=new-session; Path=/"},
        )

    with mock_client(handler) as first:
        first.bootstrap()
    with mock_client(handler) as second:
        second.bootstrap()

    assert home_cookies == [None, None]


def test_bootstrap_switches_language_and_keeps_home_html(
    mock_client: Callable[[Handler], MpkClient],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/Calendar/":
            return httpx.Response(
                200,
                text="original home",
                headers={"set-cookie": "ASP.NET_SessionId=session-123; Path=/"},
            )
        assert request.url.path == "/Calendar/ChangeLanguage"
        assert request.url.params.get("languageId") == "2"
        assert request.headers["cookie"] == "ASP.NET_SessionId=session-123"
        return httpx.Response(
            200,
            text="language fragment",
            headers={"set-cookie": "CalendarLanguageCookie=2; Path=/"},
        )

    with mock_client(handler, lang_id=2) as client:
        assert client.bootstrap() == "original home"
        assert client._client.cookies["CalendarLanguageCookie"] == "2"

    assert len(requests) == 2


def test_post_sends_urlencoded_content_without_rewriting(
    mock_client: Callable[[Handler], MpkClient],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/Calendar/CalSearch"
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.content == b"SearchText=first+aid&City=1&City=2"
        return httpx.Response(200, text="results")

    with mock_client(handler) as client:
        response = client.post(
            "/Calendar/CalSearch",
            content="SearchText=first+aid&City=1&City=2",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.text == "results"


@pytest.mark.parametrize("method", ["get", "post"])
def test_requests_raise_for_http_status_errors(
    mock_client: Callable[[Handler], MpkClient], method: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with mock_client(handler) as client, pytest.raises(httpx.HTTPStatusError) as exc_info:
        getattr(client, method)("/failure")

    assert exc_info.value.response.status_code == 503
    assert exc_info.value.request.url == "https://koulutuskalenteri.mpk.fi/failure"


def test_context_manager_closes_client_after_exception(
    mock_client: Callable[[Handler], MpkClient],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    client = mock_client(handler)
    with pytest.raises(RuntimeError, match="boom"), client as entered:
        assert entered is client
        assert not client._client.is_closed
        raise RuntimeError("boom")

    assert client._client.is_closed
