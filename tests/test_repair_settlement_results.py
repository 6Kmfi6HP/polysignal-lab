"""
Input: scripts.repair_settlement_results, factories, polysignal_lab.domain.paper_result
Output: test_settle_for_repair_returns_parseable_trade_result_row
Pos: Test Layer - Unit tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from factories import sample_market

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.paper_result import parse_paper_trade_result_row
from polysignal_lab.paper.settlement_sources import ResolutionDecision


def _repair_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "repair_settlement_results.py"
    spec = importlib.util.spec_from_file_location(
        "repair_settlement_results_for_test",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_settle_for_repair_returns_parseable_trade_result_row() -> None:
    market = sample_market()
    token = market.token_for(Side.UP)
    position = {
        "paper_position_id": "pos-repair-1",
        "position_id": "pos-repair-1",
        "signal_id": "sig-repair-1",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "token_id": token.token_id,
        "side": Side.UP.value,
        "entry_price": 0.4,
        "shares": 25.0,
        "stake_usdc": 10.0,
        "opened_at": "2026-06-22T00:00:00+00:00",
    }
    decision = ResolutionDecision(
        market_id=market.market_id,
        condition_id=market.condition_id,
        status="resolved",
        source="chain",
        outcome_values_by_token={token.token_id: 1.0},
        conflict=False,
        conflict_sources=(),
        details={},
    )

    module = _repair_module()
    result = module._settle_for_repair(position, market, decision)

    assert result is not None
    parsed = parse_paper_trade_result_row(result)
    assert parsed.get("paper_trade_id")
    assert parsed.get("signal_id") == "sig-repair-1"


def test_settle_for_repair_rejects_incomplete_position_money_fields() -> None:
    market = sample_market()
    token = market.token_for(Side.UP)
    position = {
        "paper_position_id": "pos-incomplete",
        "position_id": "pos-incomplete",
        "signal_id": "sig-incomplete",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "token_id": token.token_id,
        "side": Side.UP.value,
        "opened_at": "2026-06-22T00:00:00+00:00",
    }
    decision = ResolutionDecision(
        market_id=market.market_id,
        condition_id=market.condition_id,
        status="resolved",
        source="chain",
        outcome_values_by_token={token.token_id: 1.0},
        conflict=False,
        conflict_sources=(),
        details={},
    )

    module = _repair_module()

    assert module._settle_for_repair(position, market, decision) is None


def test_settle_for_repair_uses_event_timestamp_when_opened_at_missing() -> None:
    market = sample_market()
    token = market.token_for(Side.UP)
    position = {
        "paper_position_id": "pos-created-at",
        "position_id": "pos-created-at",
        "signal_id": "sig-created-at",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "token_id": token.token_id,
        "side": Side.UP.value,
        "entry_price": 0.4,
        "shares": 25.0,
        "stake_usdc": 10.0,
        "created_at": "2026-06-22T00:00:00+00:00",
    }
    decision = ResolutionDecision(
        market_id=market.market_id,
        condition_id=market.condition_id,
        status="resolved",
        source="chain",
        outcome_values_by_token={token.token_id: 1.0},
        conflict=False,
        conflict_sources=(),
        details={},
    )

    module = _repair_module()
    result = module._settle_for_repair(position, market, decision)

    assert result is not None
    parsed = parse_paper_trade_result_row(result)
    assert parsed.get("opened_at") == "2026-06-22T00:00:00+00:00"


def test_settle_for_repair_rejects_position_without_side() -> None:
    market = sample_market()
    token = market.token_for(Side.UP)
    position = {
        "paper_position_id": "pos-no-side",
        "position_id": "pos-no-side",
        "signal_id": "sig-no-side",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": market.market_id,
        "market_slug": market.market_slug,
        "token_id": token.token_id,
        "entry_price": 0.4,
        "shares": 25.0,
        "stake_usdc": 10.0,
        "opened_at": "2026-06-22T00:00:00+00:00",
    }
    decision = ResolutionDecision(
        market_id=market.market_id,
        condition_id=market.condition_id,
        status="resolved",
        source="chain",
        outcome_values_by_token={token.token_id: 1.0},
        conflict=False,
        conflict_sources=(),
        details={},
    )

    module = _repair_module()

    assert module._settle_for_repair(position, market, decision) is None
