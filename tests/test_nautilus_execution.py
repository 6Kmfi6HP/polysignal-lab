"""
Input: __future__, __future__.annotations, pathlib, pathlib.Path
Output: test_project_source_contains_no_local_paper_symbols
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from pathlib import Path


LOCAL_PAPER_FORBIDDEN_TEXT = (
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
            for symbol in LOCAL_PAPER_FORBIDDEN_TEXT
            if symbol in text
        )

    assert findings == []
