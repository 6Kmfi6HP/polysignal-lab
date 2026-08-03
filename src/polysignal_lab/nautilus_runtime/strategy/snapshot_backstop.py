from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import uuid4

from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_instrument_id,
)

logger = logging.getLogger(__name__)

_SNAPSHOT_FLAG = 32
_SNAPSHOT_BACKSTOP_TIMEOUT_SEC = 30.0


class _SnapshotBackstopOwner(Protocol):
    strategy_name: str
    registry: MarketCatalog | None
    cache: object
    _pending_snapshot_backstops: dict[str, SnapshotBackstopRequest]


@dataclass
class SnapshotBackstopRequest:
    strategy: str
    condition: str | None
    instrument_id: str
    token: str | None
    request_id: str
    started_at: float
    historical_ts_event: int | None = None

    def log_context(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "condition": self.condition,
            "instrument_id": self.instrument_id,
            "token": self.token,
            "request_id": self.request_id,
        }


def begin(
    strategy: _SnapshotBackstopOwner,
    instrument_id: object,
    *,
    depth: int | None,
) -> SnapshotBackstopRequest:
    instrument_key = str(instrument_id)
    fail(strategy, instrument_key, reason="superseded")
    condition, token = _context(getattr(strategy, "registry", None), instrument_key)
    request = SnapshotBackstopRequest(
        strategy=strategy.strategy_name,
        condition=condition,
        instrument_id=instrument_key,
        token=token,
        request_id=str(uuid4()),
        started_at=time.monotonic(),
    )
    _pending(strategy)[instrument_key] = request
    logger.info(
        "book_snapshot_backstop_requested",
        extra={**_event_fields(strategy, request), "depth": depth},
    )
    return request


def record_historical(strategy: _SnapshotBackstopOwner, data: object) -> bool:
    instrument_key = str(getattr(data, "instrument_id", ""))
    request = _pending(strategy).get(instrument_key)
    if request is None:
        return False
    request.historical_ts_event = _source_ts_event(data)
    logger.info(
        "book_snapshot_backstop_historical_received",
        extra=_event_fields(strategy, request, data=data),
    )
    return True


def record_live_applied(strategy: _SnapshotBackstopOwner, deltas: object) -> None:
    if not int(getattr(deltas, "flags", 0)) & _SNAPSHOT_FLAG:
        return
    instrument_key = str(getattr(deltas, "instrument_id", ""))
    request = _pending(strategy).get(instrument_key)
    ts_event = int(getattr(deltas, "ts_event", 0))
    if request is None or request.historical_ts_event != ts_event:
        return
    _ = _pending(strategy).pop(instrument_key, None)
    logger.info(
        "book_snapshot_backstop_live_applied",
        extra=_event_fields(strategy, request, data=deltas),
    )


def fail(
    strategy: _SnapshotBackstopOwner,
    instrument_key: str,
    *,
    reason: str,
    exc_info: bool = False,
) -> None:
    request = _pending(strategy).pop(instrument_key, None)
    if request is None:
        return
    logger.error(
        "book_snapshot_backstop_failed",
        extra={
            **_event_fields(strategy, request),
            "reason": reason,
        },
        exc_info=exc_info,
    )


def fail_all(strategy: _SnapshotBackstopOwner, *, reason: str) -> None:
    for instrument_key in tuple(_pending(strategy)):
        fail(strategy, instrument_key, reason=reason)


def expire(strategy: _SnapshotBackstopOwner) -> None:
    now = time.monotonic()
    expired = [
        instrument_key
        for instrument_key, request in _pending(strategy).items()
        if now - request.started_at >= _SNAPSHOT_BACKSTOP_TIMEOUT_SEC
    ]
    for instrument_key in expired:
        fail(strategy, instrument_key, reason="timeout")


def _pending(
    strategy: _SnapshotBackstopOwner,
) -> dict[str, SnapshotBackstopRequest]:
    pending = getattr(strategy, "_pending_snapshot_backstops", None)
    if pending is None:
        pending = {}
        strategy._pending_snapshot_backstops = pending
    return pending


def _context(
    registry: MarketCatalog | None,
    instrument_key: str,
) -> tuple[str | None, str | None]:
    if registry is None:
        return None, None
    for condition_id in registry.condition_ids():
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token in (pair.up, pair.down):
            if registry.instrument_id_for_token(token.token_id) == instrument_key:
                return condition_id, token.token_id
    return None, None


def _book_metrics(
    strategy: _SnapshotBackstopOwner,
    instrument_key: str,
) -> dict[str, int]:
    getter = getattr(getattr(strategy, "cache", None), "order_book", None)
    if not callable(getter):
        return {"bid_levels": 0, "ask_levels": 0, "ts_event": 0, "ts_init": 0}
    try:
        book = getter(_nautilus_instrument_id(instrument_key))
    except LookupError:
        return {"bid_levels": 0, "ask_levels": 0, "ts_event": 0, "ts_init": 0}
    return {
        "bid_levels": _level_count(book, "bids"),
        "ask_levels": _level_count(book, "asks"),
        "ts_event": int(getattr(book, "ts_event", 0)),
        "ts_init": int(getattr(book, "ts_init", 0)),
    }


def _event_fields(
    strategy: _SnapshotBackstopOwner,
    request: SnapshotBackstopRequest,
    *,
    data: object | None = None,
) -> dict[str, object]:
    fields = {
        **request.log_context(),
        "latency_ms": _latency_ms(request),
        **_book_metrics(strategy, request.instrument_id),
    }
    if data is not None:
        fields["ts_event"] = _source_ts_event(data)
        fields["ts_init"] = int(getattr(data, "ts_init", 0))
    return fields


def _source_ts_event(data: object) -> int:
    return int(getattr(data, "ts_event", getattr(data, "ts_last", 0)))


def _level_count(book: object, name: str) -> int:
    raw = getattr(book, name, ())
    if callable(raw):
        raw = raw()
    try:
        return sum(1 for _ in cast(Iterable[object], raw))
    except TypeError:
        return 0


def _latency_ms(request: SnapshotBackstopRequest) -> float:
    return round((time.monotonic() - request.started_at) * 1000, 3)
