from __future__ import annotations

import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail accidental network access unless a test is explicitly marked live."""
    if request.node.get_closest_marker("live") is not None:
        return

    def blocked_connect(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Network access is blocked in offline tests")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
