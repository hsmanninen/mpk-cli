from __future__ import annotations

import socket

import pytest


def test_network_is_blocked_by_default() -> None:
    with pytest.raises(RuntimeError, match="blocked in offline tests"):
        socket.create_connection(("127.0.0.1", 9))
