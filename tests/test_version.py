from __future__ import annotations

from importlib.metadata import version

import mpk


def test_runtime_version_uses_distribution_metadata() -> None:
    assert mpk.__version__ == version("mpk-cli")
