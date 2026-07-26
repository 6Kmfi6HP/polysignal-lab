from __future__ import annotations

import importlib.util
import os
import sys

import pytest


def require_nautilus() -> None:
    required = os.environ.get("NAUTILUS_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if sys.version_info < (3, 12):
        message = "nautilus_trader requires Python 3.12+"
        if required:
            pytest.fail(message)
        pytest.skip(message)
    if importlib.util.find_spec("nautilus_trader") is None:
        message = "nautilus_trader is not installed"
        if required:
            pytest.fail(message)
        pytest.skip(message)
