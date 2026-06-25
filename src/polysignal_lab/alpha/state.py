from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping


def json_safe_state(value: Any) -> Any:
    """Recursively convert a domain value into JSON-safe primitives.

    Deterministic: ``Enum`` -> ``.value``, ``datetime`` -> UTC ISO string,
    ``deque``/``tuple``/``set`` -> list (sets sorted), ``Mapping`` -> dict with
    string keys. Primitives passthrough. No pickle.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, deque):
        return [json_safe_state(item) for item in value]
    if isinstance(value, set):
        return [json_safe_state(item) for item in sorted(value)]
    if isinstance(value, (tuple, list)):
        return [json_safe_state(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): json_safe_state(val) for key, val in value.items()}
    return value


def restore_utc_datetime(value: str) -> datetime:
    """Parse an ISO datetime string and return a tz-aware (UTC) datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
