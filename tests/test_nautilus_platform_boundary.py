from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

from polysignal_lab.app import main as app_main


def test_default_import_does_not_require_nautilus() -> None:
    assert importlib.import_module("polysignal_lab") is not None


def test_nautilus_extra_is_optional_and_polymarket_scoped() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert all("nautilus_trader" not in dep for dep in data["project"]["dependencies"])
    nautilus_extra = data["project"]["optional-dependencies"]["nautilus"]

    assert nautilus_extra == [
        "nautilus_trader[polymarket]>=1.230.0; python_version >= '3.12'",
    ]


def test_cli_exposes_nautilus_mode_and_script() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "nautilus" in app_main.MODE_VALUES
    assert pyproject["project"]["scripts"]["polysignal-nautilus"] == "polysignal_lab.nautilus_runtime.node:main"


def test_default_source_keeps_forbidden_live_symbols_out_of_runtime() -> None:
    forbidden = (
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
    scanned_roots = [Path("src/polysignal_lab/nautilus_runtime"), Path("src/polysignal_lab/nautilus_bridge")]
    findings: list[str] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_default_nautilus_runtime_source_avoids_local_paper_executors() -> None:
    forbidden = (
        "from polysignal_lab.paper.order_intent_executor import",
        "BestAskTakerExecutor",
        "PassiveGtdExecutor",
        "PaperSimulator",
        "PolySignalPaperExecutionClient(",
    )
    allowed_files = {
        Path("src/polysignal_lab/nautilus_runtime/execution.py"),
    }
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
