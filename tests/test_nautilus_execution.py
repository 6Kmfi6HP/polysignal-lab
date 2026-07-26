from __future__ import annotations

from pathlib import Path


LEGACY_TRADING_FORBIDDEN_TEXT = (
    "from polysignal_lab.paper.order_intent_executor import",
    "BestAskTakerExecutor",
    "PassiveGtdExecutor",
    "PaperSimulator",
    "from polysignal_lab.paper.wallet import",
    "PaperWallet(",
    "BestAskTakerFillModel",
    "PaperExecutionPreflight",
    "PaperExitEngine",
    "PaperSettlementEngine(self.wallet)",
    "scheduler.wallet",
    "scheduler.paper",
    "paper_portfolio.process_signal",
    "paper_portfolio.tick_resting_orders",
)


def test_project_source_contains_no_local_paper_symbols() -> None:
    findings: list[str] = []
    source_root = Path("src/polysignal_lab")
    for path in source_root.rglob("*.py"):
        if path.name == "safety.py":
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(
            f"{path}:{symbol}"
            for symbol in LEGACY_TRADING_FORBIDDEN_TEXT
            if symbol in text
        )

    assert findings == []


def test_native_runtime_contains_no_legacy_market_state_symbols() -> None:
    forbidden = (
        "OrderBookRegistry",
        "polysignal_lab.domain.orderbook",
        "polysignal_lab.data.orderbook_payload",
        "polysignal_lab.domain.trade",
        "trade_events",
        "SpotRegistry",
        "AnchorPriceService",
    )
    runtime_root = Path("src/polysignal_lab/nautilus_runtime")
    findings = [
        f"{path}:{symbol}"
        for path in runtime_root.rglob("*.py")
        for symbol in forbidden
        if symbol in path.read_text(encoding="utf-8")
    ]

    assert findings == []
