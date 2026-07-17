"""
Input: __future__, __future__.annotations, pathlib, pathlib.Path, polysignal_lab.observability.safety, polysignal_lab.observability.safety.scan
Output: test_default_nautilus_source_avoids_live_execution_symbols, test_project_source_avoids_local_paper_execution_wheels, test_safety_scan_enforces_project_wide_local_paper_isolation, test_local_paper_execution_modules_are_deleted
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from pathlib import Path

from polysignal_lab.observability.safety import scan


RUNTIME_ROOT = Path("src/polysignal_lab/nautilus_runtime")
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
    """Live credential/factory symbols are allowed only in live-gated composition."""
    findings: list[str] = []
    gated_allow = {
        Path("src/polysignal_lab/nautilus_runtime/live_node.py"),
        Path("src/polysignal_lab/nautilus_runtime/optional_imports.py"),
    }
    for root in (RUNTIME_ROOT,):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            tokens = LIVE_FORBIDDEN_TEXT
            if path in gated_allow:
                # Official pyo3 live exec factory + credential env names.
                tokens = (
                    "PolymarketLiveExecClientFactory",
                    "set_allowances.py",
                    "create_api_key.py",
                )
            findings.extend(
                f"{path}:{forbidden}"
                for forbidden in tokens
                if forbidden in text
            )

    assert findings == []
    from polysignal_lab.nautilus_runtime.live_node import SANDBOX_EXEC_CLIENT_ID

    assert SANDBOX_EXEC_CLIENT_ID != "POLYMARKET"


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


def test_local_paper_execution_modules_are_deleted() -> None:
    deleted_paths = [
        Path("src/polysignal_lab/paper/fill_model.py"),
        Path("src/polysignal_lab/paper/order_intent_executor.py"),
        Path("src/polysignal_lab/paper/simulator.py"),
        Path("src/polysignal_lab/paper/wallet.py"),
        Path("src/polysignal_lab/paper/exit_engine.py"),
        Path("src/polysignal_lab/paper/preflight.py"),
    ]

    assert [str(path) for path in deleted_paths if path.exists()] == []
