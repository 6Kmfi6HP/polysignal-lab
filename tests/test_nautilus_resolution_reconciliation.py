from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from polysignal_lab.nautilus_runtime.strategy import resolution_settlement
from polysignal_lab.nautilus_runtime.strategy.resolution_settlement import (
    ResolvedMarketEvidence,
)


class _Obs:
    def __init__(self, open_rows: list[dict[str, object]]) -> None:
        self.open_rows = open_rows
        self.settlements: list[dict[str, object]] = []

    def query_report_open_positions(self) -> list[dict[str, object]]:
        return self.open_rows

    def record_event(self, table: str, payload: object) -> object:
        if table == "settlements":
            self.settlements.append(cast(dict[str, object], payload))
            return True
        return True


class _Cache:
    def __init__(self, raw_position: object | None) -> None:
        self.raw_position = raw_position or SimpleNamespace(is_closed=False)

    def position(self, position_id: object) -> object | None:
        if str(position_id).endswith("position-persist"):
            return self.raw_position
        return None


class _Strategy:
    def __init__(self, open_rows: list[dict[str, object]]) -> None:
        self.registry = None
        self.cache = _Cache(SimpleNamespace(is_closed=False))
        self.strategy_name = "ptb_diff"
        self.id = "strategy-1"
        self._execution_mode = "sandbox"
        self._settled_position_keys: set[tuple[str, str]] = set()
        self.progress: list[str] = []
        self.observability = _Obs(open_rows)
        self.close_calls: list[tuple[object, str, dict[str, Any]]] = []

    def _note_runtime_progress(self, phase: str) -> None:
        self.progress.append(phase)

    def close_position(self, position: object, **kwargs: object) -> None:
        self.close_calls.append((position, "close", dict(kwargs)))


def _resolved_evidence() -> dict[str, ResolvedMarketEvidence]:
    return {
        "cond1": ResolvedMarketEvidence(
            condition_id="cond1",
            token_outcomes={"token_up": 1.0, "token_down": 0.0},
            raw={},
        )
    }


def _open_position_row() -> dict[str, object]:
    return {
        "report_position_id": "position-persist",
        "position_id": "position-persist",
        "status": "OPEN",
        "instrument_id": "cond1-token_down.POLYMARKET",
        "condition_id": "cond1",
        "token_id": "token_down",
        "side": "DOWN",
        "asset": "ETH",
        "timeframe": "5m",
        "market_id": "mkt1",
        "market_slug": "eth-updown-5m-cond1",
        "entry_price": 0.5,
        "shares": 20.0,
        "stake_usdc": 10.0,
        "opened_at": "2026-07-06T12:00:00Z",
    }


def test_persistent_open_position_settles_without_registry() -> None:
    strategy = _Strategy([_open_position_row()])
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        resolution_settlement,
        "_cached_fetch_condition_evidence",
        lambda condition_ids, now: _resolved_evidence(),
    )
    try:
        resolution_settlement.resolve_open_positions(
            strategy,
            now=datetime(2026, 7, 6, 12, 5, tzinfo=UTC),
        )
        resolution_settlement.resolve_open_positions(
            strategy,
            now=datetime(2026, 7, 6, 12, 6, tzinfo=UTC),
        )
    finally:
        monkeypatch.undo()

    assert len(strategy.observability.settlements) == 1
    row = strategy.observability.settlements[0]
    assert row["exit_mode"] == "RESOLUTION"
    assert row["result"] == "LOSS"
    assert row["settlement_value"] == 0.0
    assert row["report_position_id"] == "position-persist"
    assert row["strategy"] == "ptb_diff"
    assert len(strategy.close_calls) == 1
    assert strategy.close_calls[0][2]["reduce_only"] is True
