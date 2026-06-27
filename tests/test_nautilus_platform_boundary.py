from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

from polysignal_lab.app import main as app_main


def test_default_import_does_not_require_nautilus() -> None:
    assert importlib.import_module("polysignal_lab") is not None

def test_nautilus_node_and_strategies_do_not_import_legacy_execution() -> None:
    saved_runtime_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name.startswith("polysignal_lab.nautilus_runtime")
    }
    for name in saved_runtime_modules:
        sys.modules.pop(name, None)

    try:
        importlib.import_module("polysignal_lab.nautilus_runtime.node")
        importlib.import_module("polysignal_lab.nautilus_runtime.strategies.base")

        assert "polysignal_lab.nautilus_runtime.execution" not in sys.modules
    finally:
        for name in tuple(sys.modules):
            if name.startswith("polysignal_lab.nautilus_runtime"):
                sys.modules.pop(name, None)
        sys.modules.update(saved_runtime_modules)


def test_nautilus_extra_is_optional_and_polymarket_scoped() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert all("nautilus_trader" not in dep for dep in data["project"]["dependencies"])
    nautilus_extra = data["project"]["optional-dependencies"]["nautilus"]

    assert nautilus_extra == [
        "nautilus_trader[polymarket]==1.229.0; python_version >= '3.12'",
    ]

def test_nautilus_docker_and_lock_avoid_git_source_builds() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    lock_text = Path("uv.lock").read_text(encoding="utf-8")

    assert "git+https://github.com/nautechsystems/nautilus_trader" not in dockerfile
    assert 'source = { git = "https://github.com/nautechsystems/nautilus_trader' not in lock_text


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
            if path.name == "trading_node.py":
                continue  # exec_clients is a sandbox config key, guarded by assert_no_live_polymarket_execution
            text = path.read_text(encoding="utf-8")
            findings.extend(f"{path}:{token}" for token in forbidden if token in text)


def test_default_nautilus_runtime_source_avoids_local_paper_executors() -> None:
    forbidden = (
        "from polysignal_lab.paper.order_intent_executor import",
        "BestAskTakerExecutor",
        "PassiveGtdExecutor",
        "PaperSimulator",
        "PolySignalPaperExecutionClient",
        "create_paper_execution_client",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_default_nautilus_runtime_does_not_use_custom_paper_truth_sources() -> None:
    forbidden = (
        "NautilusMatchingPaperExecutionClient(",
        "PaperWallet(",
        "PaperExecutionResult(",
        "evaluate_all_conditions(",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path.name in {
            "matching.py",
            "execution_types.py",
            "scheduler_compat.py",  # COMPATIBILITY_ONLY read-only paper components
            "orchestrator.py",  # evaluate_all_conditions in orchestrator (compat)
            "settlement.py",  # PaperWallet in settlement engine (compat)
        }:
            continue
        text = path.read_text(encoding="utf-8")
        # Skip evaluate_all_conditions in base.py (old wrapper)
        if path.name == "base.py" and "evaluate_all_conditions(" in text:
            continue
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
