"""Single source of truth for missing-value semantics and collapse counting.

Present candidates include numeric zero and False; absent candidates are None
and "". Identifier lookup also treats whitespace-only strings as absent.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polysignal_lab.observability.health import HealthRegistry

COLLAPSE_COMPONENT = "missing_values"

__all__ = [
    "COLLAPSE_COMPONENT",
    "MissingIdentifierError",
    "bind_missing_value_counter",
    "missing_value_counter",
    "count_collapse",
    "identifier",
    "display",
    "number",
    "set_number",
]

# Module-level binding mirrors runtime observability; unbound means conversions
# still work, but collapses are not counted.
_missing_value_counter: HealthRegistry | None = None


class MissingIdentifierError(ValueError):
    """Raised when identifier lookup finds no present candidate."""


def bind_missing_value_counter(registry: HealthRegistry | None) -> None:
    """Bind or clear the process-local missing-value counter."""
    global _missing_value_counter
    _missing_value_counter = registry


def missing_value_counter() -> HealthRegistry | None:
    """Return the process-local missing-value counter, if bound."""
    return _missing_value_counter


def count_collapse(key: str) -> None:
    """Record a single missing-value collapse for ``key`` when a counter is bound.

    When no counter is bound the call is a silent no-op, so callers can always
    invoke it without guarding against an unbound registry.
    """
    counter = missing_value_counter()
    if counter is not None:
        counter.inc_metric(COLLAPSE_COMPONENT, f"collapsed_{key}")


def _present(value: object) -> bool:
    return value is not None and value != ""


def _present_identifier(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return _present(value)


def identifier(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
    *keys: str,
    metric_keys: tuple[str, ...] = (),
    source: str = "",
) -> str:
    """Return the first present identifier candidate, stripped of whitespace."""
    for source_mapping, names in ((row, keys), (metrics, metric_keys)):
        for key in names:
            value = source_mapping.get(key)
            if _present_identifier(value):
                return str(value).strip()
    field = keys[0] if keys else metric_keys[0] if metric_keys else ""
    details = " from ".join(detail for detail in (field, source) if detail)
    raise MissingIdentifierError(
        f"missing identifier: {details}" if details else "missing identifier"
    )


def display(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
    *keys: str,
    metric_keys: tuple[str, ...] = (),
) -> str:
    """Return the string form of the first present candidate, or an empty string."""
    for source_mapping, names in ((row, keys), (metrics, metric_keys)):
        for key in names:
            value = source_mapping.get(key)
            if _present(value):
                return str(value)
    return ""


def number(
    row: Mapping[str, object],
    metrics: Mapping[str, object],
    *keys: str,
    metric_keys: tuple[str, ...] = (),
) -> float | None:
    """Return the first finite float value, or None when none is present."""
    for source_mapping, names in ((row, keys), (metrics, metric_keys)):
        for key in names:
            value = source_mapping.get(key)
            if not _present(value):
                continue
            try:
                parsed = float(str(value))
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                return parsed
    return None


def set_number(
    payload: dict[str, object],
    key: str,
    value: float | None,
) -> None:
    """Store a finite value and count non-finite or missing values as collapses."""
    if value is not None and math.isfinite(value):
        payload[key] = value
        return
    count_collapse(key)
