from __future__ import annotations

from pathlib import Path

from polysignal_lab.observability.safety import scan


RUNTIME_ROOT = Path("src/polysignal_lab/nautilus_runtime")
BRIDGE_ROOT = Path("src/polysignal_lab/nautilus_bridge")
LIVE_FORBIDDEN_TEXT = (
    "PolymarketExecutionClient",
    "PolymarketLiveExecClientFactory",
    "POLYMARKET_PK",
    "POLYMARKET_FUNDER",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_PASSPHRASE",
    "set_allowances.py",
    "create_api_key.py",
)


def test_default_nautilus_source_avoids_live_execution_symbols() -> None:
    findings: list[str] = []
    for root in (RUNTIME_ROOT, BRIDGE_ROOT):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            findings.extend(
                f"{path}:{forbidden}"
                for forbidden in LIVE_FORBIDDEN_TEXT
                if forbidden in text
            )

    assert findings == []
    from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID

    assert PAPER_EXEC_CLIENT_ID != "POLYMARKET"


def test_project_source_avoids_local_paper_execution_wheels() -> None:
    findings: list[str] = []
    source_root = Path("src/polysignal_lab")
    forbidden = (
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
    for path in source_root.rglob("*.py"):
        if path.name == "safety.py":
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(
            f"{path}:{symbol}"
            for symbol in forbidden
            if symbol in text
        )

    assert findings == []


def test_safety_scan_enforces_project_wide_local_paper_isolation(tmp_path: Path) -> None:
    source_root = tmp_path / "src" / "polysignal_lab" / "app"
    source_root.mkdir(parents=True)
    (source_root / "scheduler.py").write_text(
        "from polysignal_lab.paper.simulator import PaperSimulator\n"
        "def f(scheduler):\n"
        "    scheduler.wallet = object()\n",
        encoding="utf-8",
    )

    assert sorted(scan(tmp_path)) == [
        (
            "src/polysignal_lab/app/scheduler.py",
            "PaperSimulator",
        ),
        (
            "src/polysignal_lab/app/scheduler.py",
            "scheduler.wallet",
        ),
    ]
