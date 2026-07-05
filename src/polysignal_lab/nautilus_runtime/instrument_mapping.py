from __future__ import annotations

from importlib import import_module
from typing import Callable, cast


POLYMARKET_VENUE = "POLYMARKET"


def polymarket_instrument_id(condition_id: str, token_id: str) -> str:
    condition = str(condition_id).strip()
    token = str(token_id).strip()
    if not condition:
        raise ValueError("condition_id must not be empty")
    if not token:
        raise ValueError("token_id must not be empty")
    try:
        helper = getattr(
            import_module("nautilus_trader.adapters.polymarket"),
            "get_polymarket_instrument_id",
        )
    except (ModuleNotFoundError, AttributeError) as exc:
        raise RuntimeError(
            "Nautilus Polymarket adapter is required to resolve instrument IDs"
        ) from exc
    return str(cast(Callable[[str, str], object], helper)(condition, token))
