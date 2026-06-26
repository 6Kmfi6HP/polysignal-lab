from __future__ import annotations

from pathlib import Path

from polysignal_lab.observability.safety import scan


RUNTIME_ROOT = Path("src/polysignal_lab/nautilus_runtime")
BRIDGE_ROOT = Path("src/polysignal_lab/nautilus_bridge")
LIVE_FORBIDDEN_TEXT = (
    "PolymarketExecutionClient",
    "PolymarketLiveExecClientFactory",
    "exec_clients",
    "POLYMARKET_PK",
    "POLYMARKET_FUNDER",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_PASSPHRASE",
    "set_allowances.py",
    "create_api_key.py",
)
LOCAL_PAPER_FORBIDDEN_TEXT = (
    "BestAskTakerExecutor",
    "PassiveGtdExecutor",
    "PaperSimulator",
    "PolySignalPaperExecutionClient(",
)
LOCAL_PAPER_ALLOWED_FILES = {
    RUNTIME_ROOT / "execution.py",
}


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


def test_default_nautilus_runtime_avoids_local_paper_executors() -> None:
    findings: list[str] = []
    for path in RUNTIME_ROOT.rglob("*.py"):
        if path in LOCAL_PAPER_ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(
            f"{path}:{forbidden}"
            for forbidden in LOCAL_PAPER_FORBIDDEN_TEXT
            if forbidden in text
        )

    assert findings == []


def test_safety_scan_enforces_default_runtime_local_paper_isolation(tmp_path: Path) -> None:
    runtime_root = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "node.py").write_text(
        "from polysignal_lab.paper.order_intent_executor import BestAskTakerExecutor\n",
        encoding="utf-8",
    )
    (runtime_root / "execution.py").write_text(
        "from polysignal_lab.paper.order_intent_executor import BestAskTakerExecutor\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [
        (
            "src/polysignal_lab/nautilus_runtime/node.py",
            "BestAskTakerExecutor",
        )
    ]
