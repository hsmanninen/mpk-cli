"""mpk: command-line search for the MPK Koulutuskalenteri."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mpk-cli")
except PackageNotFoundError:
    __version__ = "0.2.0"
