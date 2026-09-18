"""TDD: sparse ``report_positions`` rows settle via registry enrichment.

Rows persisted by ``report_positions`` often omit ``side``/``market_id``/
``market_slug``/``asset``/``timeframe``. ``_candidate_from_report_position``
used to drop such sparse rows on two gates (empty ``side`` and incomplete
metadata), yielding zero candidates and an idle ``resolve_open_positions``.

The fix backfills missing fields at *read* time from the in-memory
``MarketCatalog`` registry -- the same pattern already used by
``_candidate_from_cache_position``. Inputs (row shares, registry token->side
mapping, evidence outcome) are controlled by the fakes; assertions check the
production-computed ``result``/``settlement_value``/``side`` so the test is
non-tautological.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from polysignal_lab.data.gamma_resolution import ResolvedMarketEvidence
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.strategy import resolution_settlement

NOW = datetime(2026, 7, 6, 12, 5, tzinfo=UTC)


def _pair(
    *,
    up_token_id: str,
    down_token_id: str,
    condition_id: str = "cond1",
    market_id: str = "registry-mkt",
    market_slug: str = "eth-updown-5m-cond1",
    asset: str = "ETH",
    timeframe: str = "5m",
) -> MarketPairMeta:
    return MarketPairMeta(
        market_id=market_id,
        market_slug=market_slug,
        condition_id=condition_id,
        asset=asset,
        timeframe=timeframe,
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta(token_id=up_token_id, side=Side.UP, outcome="UP"),
        down=InstrumentTokenMeta(token_id=down_token_id, side=Side.DOWN, outcome="DOWN"),
    )


def _catalog(*pairs: MarketPairMeta) -> MarketCatalog:
    catalog = MarketCatalog()
    for pair in pairs:
        catalog.register(pair)
    return catalog


def _evidence(*, up_wins: bool) -> dict[str, ResolvedMarketEvidence]:
    token_outcomes = {"token_up": 1.0, "token_down": 0.0} if up_wins else {
        "token_up": 0.0,
        "token_down": 1.0,
    }
    return {
        "cond1": ResolvedMarketEvidence(
            condition_id="cond1",
            token_outcomes=token_outcomes,
            raw={},
        )
    }


class _Obs:
    def __init__(self, open_rows: list[dict[str, object]]) -> None:
        self.open_rows = open_rows
        self.settlements: list[dict[str, object]] = []

    def query_report_open_positions(self) -> list[dict[str, object]]:
        return self.open_rows

    def record_event(self, table: str, payload: object) -> object:
        if table == "settlements":
            self.settlements.append(payload)  # type: ignore[arg-type]
            return True
        return True


class _Cache:
    def __init__(self, raw_position: object | None) -> None:
        self.raw_position = raw_position or SimpleNamespace(is_closed=False)

    def position(self, position_id: object) -> object | None:
        if str(position_id).endswith("pos-1"):
            return self.raw_position
        return None


class _Strategy:
    def __init__(
        self,
        open_rows: list[dict[str, object]],
        registry: object | None,
    ) -> None:
        self.registry = registry
        self.cache = _Cache(SimpleNamespace(is_closed=False))
        self.strategy_name = "ptb_diff"
        self.id: object = "strategy-1"
        self.strategy_id: object = "strategy-1"
        self._execution_mode = "sandbox"
        self._settled_position_keys: set[tuple[str, str]] = set()
        self._progress: list[str] = []
        self.observability = _Obs(open_rows)
        self.close_calls: list[tuple[object, dict[str, Any]]] = []

    def _note_runtime_progress(self, phase: str) -> None:
        self._progress.append(phase)

    def close_position(self, position: object, **kwargs: object) -> None:
        self.close_calls.append((position, dict(kwargs)))


def _run(strategy: _Strategy, *, up_wins: bool) -> None:
    resolution_settlement.resolve_open_positions(
        strategy,
        now=NOW,
        fetch_evidence=lambda condition_ids, *, now: _evidence(up_wins=up_wins),
    )


def test_sparse_report_position_settles_via_registry() -> None:
    """Sparse OPEN row (no side/market fields) settles once the registry
    backfills ``side`` (from token) and market metadata."""
    registry = _catalog(
        _pair(up_token_id="token_up", down_token_id="token_down"),
    )
    sparse_row: dict[str, object] = {
        "report_position_id": "rp-1",
        "position_id": "pos-1",
        "status": "OPEN",
        "instrument_id": "cond1-token_up.POLYMARKET",
        "entry_price": 0.5,
        "shares": 20.0,
        "stake_usdc": 10.0,
        "opened_at": "2026-07-06T12:00:00Z",
    }
    strategy = _Strategy([sparse_row], registry=registry)

    _run(strategy, up_wins=True)

    assert len(strategy.observability.settlements) == 1, strategy._progress
    row = strategy.observability.settlements[0]
    assert row["exit_mode"] == "RESOLUTION"
    assert row["result"] == "WIN"
    assert row["settlement_value"] == 20.0
    assert row["report_position_id"] == "rp-1"
    assert row["strategy"] == "ptb_diff"
    # side + market metadata must come from the registry, not the (sparse) row.
    assert row["side"] == "UP"
    assert row["market_id"] == "registry-mkt"
    assert row["market_slug"] == "eth-updown-5m-cond1"
    assert row["asset"] == "ETH"
    assert row["timeframe"] == "5m"
    assert len(strategy.close_calls) == 1
    assert strategy.close_calls[0][1]["reduce_only"] is True


def test_registry_enrichment_does_not_clobber_present_fields() -> None:
    """Enrichment fills only *missing* fields; row-truth (``side``/market
    metadata) must never be overwritten with registry meta. A clobbering
    implementation would emit the registry's market_id/asset/timeframe here."""
    registry = _catalog(
        _pair(up_token_id="token_up", down_token_id="token_down"),
    )
    rich_row: dict[str, object] = {
        "report_position_id": "rp-2",
        "position_id": "pos-1",
        "status": "OPEN",
        "instrument_id": "cond1-token_up.POLYMARKET",
        "side": "UP",
        "market_id": "row-mkt",
        "market_slug": "row-slug",
        "asset": "BTC",
        "timeframe": "1h",
        "entry_price": 0.5,
        "shares": 20.0,
        "stake_usdc": 10.0,
        "opened_at": "2026-07-06T12:00:00Z",
    }
    strategy = _Strategy([rich_row], registry=registry)

    _run(strategy, up_wins=True)

    assert len(strategy.observability.settlements) == 1, strategy._progress
    row = strategy.observability.settlements[0]
    # Row-truth preserved; registry meta (registry-mkt/ETH/5m) not applied.
    assert row["side"] == "UP"
    assert row["market_id"] == "row-mkt"
    assert row["market_slug"] == "row-slug"
    assert row["asset"] == "BTC"
    assert row["timeframe"] == "1h"
    assert row["report_position_id"] == "rp-2"
    # Outcome still derives from the token, not the clobbered metadata.
    assert row["result"] == "WIN"
    assert row["settlement_value"] == 20.0


def test_rich_row_settles_without_registry() -> None:
    """registry=None must keep settling fully-populated rows -- regression
    guard for threading the registry through the report-position path."""
    rich_row: dict[str, object] = {
        "report_position_id": "rp-3",
        "position_id": "pos-1",
        "status": "OPEN",
        "instrument_id": "cond1-token_up.POLYMARKET",
        "side": "UP",
        "market_id": "mkt1",
        "market_slug": "eth-updown-5m-cond1",
        "asset": "ETH",
        "timeframe": "5m",
        "entry_price": 0.4,
        "shares": 25.0,
        "stake_usdc": 10.0,
        "opened_at": "2026-07-06T12:00:00Z",
    }
    strategy = _Strategy([rich_row], registry=None)

    _run(strategy, up_wins=True)

    assert len(strategy.observability.settlements) == 1, strategy._progress
    row = strategy.observability.settlements[0]
    assert row["exit_mode"] == "RESOLUTION"
    assert row["result"] == "WIN"
    assert row["settlement_value"] == 25.0
    assert row["side"] == "UP"
    assert row["market_id"] == "mkt1"
