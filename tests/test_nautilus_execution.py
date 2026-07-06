from __future__ import annotations

import importlib
import sys
from pathlib import Path

from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision


LOCAL_PAPER_ENGINE_MODULES = {
    "polysignal_lab.paper.order_intent_executor",
    "polysignal_lab.paper.simulator",
    "polysignal_lab.paper.wallet",
}

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


def test_execution_import_does_not_load_local_paper_engine_modules() -> None:
    for module_name in {
        "polysignal_lab.nautilus_runtime.execution",
        *LOCAL_PAPER_ENGINE_MODULES,
    }:
        sys.modules.pop(module_name, None)

    execution = importlib.import_module("polysignal_lab.nautilus_runtime.execution")

    assert execution.order_spec_from_decision is order_spec_from_decision
    assert not hasattr(execution, "PaperExecutionResult")
    assert LOCAL_PAPER_ENGINE_MODULES.isdisjoint(sys.modules)


def test_execution_module_does_not_export_legacy_local_paper_client() -> None:
    execution = importlib.import_module("polysignal_lab.nautilus_runtime.execution")

    assert not hasattr(execution, "PolySignalPaperExecutionClient")
    assert not hasattr(execution, "create_paper_execution_client")


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
