from __future__ import annotations

from datetime import timedelta

from polysignal_lab.domain.enums import MarketStatus, Side, TradeResultStatus
from polysignal_lab.domain.orderbook import BookLevel
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.utils import utc_now
from factories import BookFactoryConfig, sample_book


async def _signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


async def test_paper_fill_wallet_position(snapshot, books, settings):
    sig = await _signal(snapshot, settings)
    wallet = PaperWallet(starting_balance=settings.paper_trading.starting_balance_usdc)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    result = sim.process_signal(sig, books.get(sig.token_id))
    assert result.order.status == "FILLED"
    assert result.fill is not None
    assert result.position is not None
    assert wallet.cash_balance == 990.0
    assert result.fill.shares == result.order.stake_usdc / result.fill.fill_price


async def test_accepted_signal_fills_at_best_ask_and_updates_wallet(snapshot, books, settings):
    sig = await _signal(snapshot, settings)
    book = books.get(sig.token_id)
    wallet = PaperWallet(starting_balance=settings.paper_trading.starting_balance_usdc)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)

    result = sim.process_signal(sig, book)

    assert result.order.status == "FILLED"
    assert result.order.reject_reason is None
    assert result.fill is not None
    assert result.position is not None
    assert result.fill.raw_best_ask == book.best_ask
    assert result.fill.fill_price == book.best_ask + (
        book.best_ask * settings.paper_trading.fill_model.slippage_bps / 10000
    )
    assert wallet.cash_balance == 990.0
    assert wallet.equity == 1000.0
    assert wallet.open_position_count == 1
    assert wallet.exposure_by_market(sig.market_id) == 10.0
    assert wallet.exposure_by_strategy(sig.strategy) == 10.0
    assert result.order.metrics["fill_decision_reason"] == "FILLED"
    assert result.order.metrics["available_depth_usdc"] >= result.order.stake_usdc


async def test_paper_rejects_ask_above_max(snapshot, books, settings):
    sig = (await _signal(snapshot, settings)).model_copy(update={"max_entry_price": 0.50})
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    result = sim.process_signal(sig, books.get(sig.token_id))
    assert result.order.status == "REJECTED"
    assert result.order.reject_reason == "PAPER_ENTRY_PRICE_MOVED"
    assert result.order.metrics["paper_original_reason"] == "ASK_ABOVE_MAX_ENTRY"
    assert result.order.metrics["paper_normalized_reason"] == "PAPER_ENTRY_PRICE_MOVED"


async def test_paper_rejects_insufficient_cash(snapshot, books, settings):
    sig = await _signal(snapshot, settings)
    wallet = PaperWallet(starting_balance=1)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    result = sim.process_signal(sig, books.get(sig.token_id))
    assert result.order.reject_reason == "PAPER_WALLET_INSUFFICIENT_CASH"
    assert result.order.metrics["paper_original_reason"] == "WALLET_INSUFFICIENT_CASH"
    assert result.order.metrics["paper_normalized_reason"] == "PAPER_WALLET_INSUFFICIENT_CASH"


async def test_paper_rejects_insufficient_depth(snapshot, settings):
    sig = await _signal(snapshot, settings)
    book = sample_book(sig.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=1))
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    result = sim.process_signal(sig, book)
    assert result.order.reject_reason == "PAPER_DEPTH_TOO_THIN"
    assert result.order.metrics["paper_original_reason"] == "INSUFFICIENT_DEPTH"
    assert result.order.metrics["paper_normalized_reason"] == "PAPER_DEPTH_TOO_THIN"

async def test_paper_preflight_rejects_edge_vanished(snapshot, books, settings):
    sig = (await _signal(snapshot, settings)).model_copy(
        update={
            "max_entry_price": 0.90,
            "metrics": {"directional_probability": 0.83, "min_probability_edge": 0.05},
        }
    )
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)

    result = sim.process_signal(sig, books.get(sig.token_id))

    assert result.order.status == "REJECTED"
    assert result.order.reject_reason == "PAPER_EDGE_VANISHED"
    assert result.fill is None
    assert result.position is None
    assert wallet.cash_balance == 1000.0
    assert result.order.metrics["paper_edge_revalidated"] is True


async def test_stale_orderbook_rejects_fill_without_position(snapshot, books, settings):
    sig = await _signal(snapshot, settings)
    stale_book = books.get(sig.token_id).model_copy(
        update={
            "received_at": utc_now()
            - timedelta(milliseconds=settings.data.polymarket.max_book_staleness_ms + 1000)
        }
    )
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)

    result = sim.process_signal(sig, stale_book)

    assert result.order.status == "REJECTED"
    assert result.order.reject_reason == "PAPER_STALE_ORDERBOOK"
    assert result.fill is None
    assert result.position is None
    assert wallet.cash_balance == 1000.0
    assert wallet.equity == 1000.0
    assert wallet.open_position_count == 0
    assert wallet.exposure_by_market(sig.market_id) == 0.0
    assert result.order.metrics["fill_decision_reason"] == "PAPER_STALE_ORDERBOOK"
    assert result.order.metrics["paper_orderbook_fresh"] is False
    assert result.order.metrics["paper_original_reason"] == "STALE_ORDERBOOK"
    assert result.order.metrics["paper_normalized_reason"] == "PAPER_STALE_ORDERBOOK"


async def test_reconciliation_ineligibility_rejects_fills(snapshot, settings) -> None:
    from polysignal_lab.data.state import OrderBookRegistry
    from polysignal_lab.domain.enums import OrderIntent
    from polysignal_lab.domain.orderbook import OrderBook

    registry = OrderBookRegistry()
    wallet = PaperWallet(1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet, registry)

    sig = (await _signal(snapshot, settings)).model_copy(
        update={"order_intent": OrderIntent.TAKER_FOK}
    )

    # Delta before snapshot -> ineligible for fill simulation.
    delta_book = OrderBook(token_id=sig.token_id, source_timestamp="1710000000000")
    registry.update_from_delta(delta_book)
    res = sim.process_signal(sig, delta_book)

    assert res.status == "REJECTED"
    assert res.order.reject_reason == "PAPER_STALE_ORDERBOOK"
    assert res.order.metrics["paper_original_reason"] == "NO_SNAPSHOT"
    assert res.order.metrics["paper_normalized_reason"] == "PAPER_STALE_ORDERBOOK"

async def test_missing_and_malformed_orderbooks_reject_without_position(snapshot, settings):
    sig = await _signal(snapshot, settings)
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)

    missing = sim.process_signal(sig, None)
    malformed = sim.process_signal(
        sig,
        sample_book(sig.token_id).model_copy(
            update={"asks": [BookLevel(price=0.0, size=100.0)]}
        ),
    )

    assert missing.order.status == "REJECTED"
    assert missing.order.reject_reason == "PAPER_MISSING_ORDERBOOK"
    assert missing.order.metrics["paper_original_reason"] == "MISSING_ORDERBOOK"
    assert missing.order.metrics["paper_normalized_reason"] == "PAPER_MISSING_ORDERBOOK"
    assert malformed.order.status == "REJECTED"
    assert malformed.order.reject_reason == "PAPER_MALFORMED_ORDERBOOK"
    assert malformed.order.metrics["paper_original_reason"] == "MALFORMED_ORDERBOOK"
    assert malformed.order.metrics["paper_normalized_reason"] == "PAPER_MALFORMED_ORDERBOOK"
    assert missing.position is None
    assert malformed.position is None
    assert wallet.cash_balance == 1000.0
    assert wallet.open_position_count == 0


async def test_nan_ask_rejects_malformed_without_depth_check(snapshot, settings):
    sig = await _signal(snapshot, settings)
    settings.paper_trading.fill_model.require_depth_check = False
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    book = sample_book(sig.token_id).model_copy(
        update={"asks": [BookLevel(price=float("nan"), size=100.0)]}
    )

    result = sim.process_signal(sig, book)

    assert result.order.status == "REJECTED"
    assert result.order.reject_reason == "PAPER_MALFORMED_ORDERBOOK"
    assert result.fill is None
    assert result.position is None
    assert wallet.cash_balance == 1000.0
    assert wallet.equity == 1000.0
    assert wallet.open_position_count == 0
    assert wallet.exposure_by_market(sig.market_id) == 0.0
    assert result.order.metrics["fill_decision_reason"] == "PAPER_MALFORMED_ORDERBOOK"
    assert result.order.metrics["paper_original_reason"] == "MALFORMED_ORDERBOOK"
    assert result.order.metrics["paper_normalized_reason"] == "PAPER_MALFORMED_ORDERBOOK"


async def test_settlement_win_and_loss(snapshot, books, market, settings):
    sig = await _signal(snapshot, settings)
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    sim_result = sim.process_signal(sig, books.get(sig.token_id))
    market.resolved_outcome = Side.UP
    market.status = MarketStatus.RESOLVED
    result = PaperSettlementEngine(wallet).settle(sim_result.position, market)
    assert result.result == TradeResultStatus.WIN
    assert result.settlement_value == result.shares
    assert result.pnl_usdc == result.settlement_value - result.stake_usdc


async def test_settlement_split(snapshot, books, market, settings):
    sig = await _signal(snapshot, settings)
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    sim_result = sim.process_signal(sig, books.get(sig.token_id))
    result = PaperSettlementEngine(wallet).settle(sim_result.position, market, outcome_value=0.5)
    assert result.result == TradeResultStatus.VOID
    assert result.settlement_value == result.shares * 0.5


async def test_exit_engine_take_profit(snapshot, books, settings):
    sig = await _signal(snapshot, settings)
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    sim_result = sim.process_signal(sig, books.get(sig.token_id))
    high_bid_book = sample_book(sig.token_id, BookFactoryConfig(ask=0.97, bid=0.95, size=100))
    result = PaperExitEngine(settings.paper_trading.exit_model, wallet).evaluate(sim_result.position, high_bid_book)
    assert result is not None
    assert result.result == TradeResultStatus.WIN
