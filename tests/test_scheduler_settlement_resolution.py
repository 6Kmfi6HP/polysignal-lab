"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, types, types.SimpleNamespace, unittest.mock, unittest.mock.AsyncMock, unittest.mock.Mock, pytest, polysignal_lab.app.scheduler_reporting, polysignal_lab.app.scheduler_reporting.check_settlements
Output: test_resolved_numeric_half_payout_closes_as_void_with_provenance, test_unknown_settlement_skips_open_projection, test_cancelled_decision_uses_refund_path, test_check_settlements_is_idempotent_per_position, test_chain_conflict_settlement_logs_system_event
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.app._settlement_check import check_settlements
from polysignal_lab.domain.enums import MarketStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_result import trade_result_status
from polysignal_lab.paper.settlement_sources import ResolutionDecision


def _market(status: MarketStatus = MarketStatus.ACTIVE) -> Market:
    return Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        status=status,
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _projection(
    *,
    token_id: str = "token-up",
    side: Side = Side.UP,
    quantity: float = 25.0,
    entry_price: float = 0.40,
    stake_usdc: float = 10.0,
) -> dict[str, object]:
    return {
        "paper_position_id": "pos-1",
        "position_id": "pos-1",
        "market_id": "market-1",
        "token_id": token_id,
        "side": side.value,
        "quantity": quantity,
        "avg_entry_price": entry_price,
        "stake_usdc": stake_usdc,
        "signal_id": "sig-1",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "opened_at": "2026-06-22T00:00:00+00:00",
        "is_closed": False,
    }


def _scheduler(market: Market, decision: ResolutionDecision) -> Mock:
    scheduler = Mock()
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = decision
    scheduler.markets = SimpleNamespace(get=Mock(return_value=market), upsert_many=Mock())
    scheduler.nautilus_cache = object()
    scheduler.nautilus_portfolio = None
    scheduler.persistence.insert_paper_trade_result.return_value = None
    scheduler.persistence.append_log.return_value = None
    scheduler.persistence.insert_system_event.return_value = None
    scheduler.persistence.query_json.return_value = []
    scheduler.settings.telegram.send_paper_results = False
    return scheduler


def test_nautilus_positions_prefers_open_cache_and_enriches_catalog_identity() -> None:
    import polysignal_lab.app._settlement_check as settlement_mod
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketCatalog,
        MarketPairMeta,
    )

    catalog = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token_id: f"{token_id}.POLYMARKET"
    )
    catalog.register(
        MarketPairMeta(
            market_id="market-1",
            market_slug="slug",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("token-up", Side.UP),
            down=InstrumentTokenMeta("token-down", Side.DOWN),
        )
    )
    position = SimpleNamespace(
        id="position-1",
        instrument_id="token-up.POLYMARKET",
        signed_qty=25.0,
        avg_px_open=0.40,
        realized_pnl=0.0,
        is_closed=False,
    )
    calls: list[str] = []

    class Cache:
        def positions_open(self):
            calls.append("positions_open")
            return [position]

        def positions(self):
            calls.append("positions")
            return []

    scheduler = SimpleNamespace(nautilus_cache=Cache(), market_catalog=catalog)

    rows = settlement_mod._nautilus_positions(scheduler)

    assert calls == ["positions_open"]
    assert rows[0]["market_id"] == "market-1"
    assert rows[0]["condition_id"] == "condition-1"
    assert rows[0]["token_id"] == "token-up"
    assert rows[0]["side"] == Side.UP.value


def _patch_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override _nautilus_positions to return the default projected position dict."""
    import polysignal_lab.app._settlement_check as settlement_mod

    monkeypatch.setattr(
        settlement_mod,
        "_nautilus_positions",
        lambda s: [_projection()],
    )


@pytest.mark.anyio
async def test_unresolved_projection_side_skips_settlement(monkeypatch) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    projection = _projection(token_id="token-missing")
    del projection["side"]
    monkeypatch.setattr(settlement_mod, "_nautilus_positions", lambda s: [projection])
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-missing": 1.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.anyio
async def test_resolved_numeric_half_payout_closes_as_void_with_provenance(monkeypatch) -> None:
    _patch_positions(monkeypatch)
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 0.5, "token-down": 0.5},
            False,
            (),
            {"settlement_source": "chain", "condition_id": "0x" + "1" * 64},
        ),
    )

    results = await check_settlements(scheduler)

    assert len(results) == 1
    assert trade_result_status(results[0]) == TradeResultStatus.VOID
    assert results[0]["outcome_value"] == 0.5
    assert results[0]["settlement_value"] == 12.5
    assert results[0]["details"]["settlement_source"] == "chain"
    assert results[0]["details"]["native_settlement_mode"] == "report_only"
    assert results[0]["details"]["native_position_mutation"] == "not_supported"
    assert results[0]["details"]["native_position_status"] == "open_projection"


@pytest.mark.anyio
async def test_unknown_settlement_skips_open_projection(monkeypatch) -> None:
    _patch_positions(monkeypatch)
    decision = ResolutionDecision(
        "market-1",
        "0x" + "1" * 64,
        "unknown",
        "none",
        {},
        False,
        (),
        {"reason": "NO_RESOLVED_EVIDENCE"},
    )
    scheduler = _scheduler(_market(MarketStatus.ACTIVE), decision)

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.anyio
async def test_cancelled_decision_uses_refund_path(monkeypatch) -> None:
    _patch_positions(monkeypatch)
    scheduler = _scheduler(
        _market(MarketStatus.CLOSED),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "cancelled",
            "gamma",
            {},
            False,
            (),
            {"settlement_source": "gamma"},
        ),
    )

    results = await check_settlements(scheduler)

    assert trade_result_status(results[0]) == TradeResultStatus.VOID
    assert results[0]["outcome_value"] == 0.40
    assert results[0]["settlement_value"] == 10.0


@pytest.mark.anyio
async def test_check_settlements_is_idempotent_per_position(monkeypatch) -> None:
    _patch_positions(monkeypatch)
    stored: list[dict[str, object]] = []

    def query_json(table: str, **kwargs: object) -> list[dict[str, object]]:
        if table == "paper_trade_results":
            return list(stored)
        return []

    def insert_paper_trade_result(result: Mapping[str, object]) -> None:
        stored.append(dict(result))

    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0, "token-down": 0.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )
    scheduler.persistence.query_json = query_json
    scheduler.persistence.insert_paper_trade_result = insert_paper_trade_result

    first = await check_settlements(scheduler)
    second = await check_settlements(scheduler)

    assert len(first) == 1
    assert second == []
    assert len(stored) == 1
    assert stored[0]["paper_position_id"] == "pos-1"


@pytest.mark.anyio
async def test_chain_conflict_settlement_logs_system_event(monkeypatch) -> None:
    _patch_positions(monkeypatch)
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0, "token-down": 0.0},
            True,
            ("gamma",),
            {"settlement_source": "chain", "settlement_conflict": True},
        ),
    )

    results = await check_settlements(scheduler)

    assert trade_result_status(results[0]) == TradeResultStatus.WIN
    scheduler.persistence.insert_system_event.assert_called_once()


@pytest.mark.anyio
async def test_settlement_skips_projection_without_resolvable_side(monkeypatch) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    projection = _projection(token_id="unmapped-token")
    projection.pop("side")
    monkeypatch.setattr(settlement_mod, "_nautilus_positions", lambda s: [projection])
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"unmapped-token": 1.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.anyio
async def test_settlement_skips_projection_without_opened_timestamp(monkeypatch) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    projection = _projection()
    projection.pop("opened_at")
    monkeypatch.setattr(settlement_mod, "_nautilus_positions", lambda s: [projection])
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.anyio
async def test_settlement_skips_projection_with_invalid_opened_timestamp(monkeypatch) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    projection = _projection()
    projection["opened_at"] = "not-a-date"
    monkeypatch.setattr(settlement_mod, "_nautilus_positions", lambda s: [projection])
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.parametrize("field", ["quantity", "avg_entry_price", "stake_usdc"])
@pytest.mark.anyio
async def test_settlement_skips_projection_with_missing_money_field(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    projection = _projection()
    projection.pop(field)
    monkeypatch.setattr(settlement_mod, "_nautilus_positions", lambda s: [projection])
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", float("nan")),
        ("avg_entry_price", float("inf")),
        ("stake_usdc", float("nan")),
        ("quantity", 0.0),
        ("avg_entry_price", 0.0),
        ("stake_usdc", 0.0),
    ],
)
@pytest.mark.anyio
async def test_settlement_skips_projection_with_invalid_numeric_money(
    monkeypatch: pytest.MonkeyPatch, field: str, value: float
) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    projection = _projection()
    projection[field] = value
    monkeypatch.setattr(settlement_mod, "_nautilus_positions", lambda s: [projection])
    scheduler = _scheduler(
        _market(),
        ResolutionDecision(
            "market-1",
            "0x" + "1" * 64,
            "resolved",
            "chain",
            {"token-up": 1.0},
            False,
            (),
            {"settlement_source": "chain"},
        ),
    )

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.persistence.insert_paper_trade_result.assert_not_called()
