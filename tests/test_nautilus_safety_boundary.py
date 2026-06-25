from __future__ import annotations

from pathlib import Path

BRIDGE_ROOT = Path("src/polysignal_lab/nautilus_bridge")
FORBIDDEN_TEXT = (
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


def test_nautilus_bridge_default_source_avoids_live_execution_symbols() -> None:
    findings: list[str] = []
    for path in BRIDGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_TEXT:
            if forbidden in text:
                findings.append(f"{path}:{forbidden}")

    assert findings == []
