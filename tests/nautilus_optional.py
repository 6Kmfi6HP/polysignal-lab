from __future__ import annotations

import importlib.util
import sys

import pytest


def require_nautilus() -> None:
    if sys.version_info < (3, 12):
        pytest.skip("nautilus_trader requires Python 3.12+")
    if importlib.util.find_spec("nautilus_trader") is None:
        pytest.skip("nautilus_trader is not installed")
