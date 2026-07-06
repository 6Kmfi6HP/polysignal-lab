from __future__ import annotations

import importlib
import sys
import tomllib
import pytest
from pathlib import Path
from typing import cast

from polysignal_lab.app import main as app_main


def test_default_import_does_not_require_nautilus() -> None:
    assert importlib.import_module("polysignal_lab") is not None

def test_nautilus_node_and_strategies_do_not_import_legacy_execution() -> None:
    root_pkg = importlib.import_module("polysignal_lab")
    missing_runtime_attr = not hasattr(root_pkg, "nautilus_runtime")
    saved_runtime_attr = getattr(root_pkg, "nautilus_runtime", None)
    saved_runtime_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name.startswith("polysignal_lab.nautilus_runtime")
    }
    for name in saved_runtime_modules:
        _ = sys.modules.pop(name, None)

    try:
        _ = importlib.import_module("polysignal_lab.nautilus_runtime.node")
        assert "polysignal_lab.nautilus_runtime.strategies.base" not in sys.modules
        assert "polysignal_lab.nautilus_runtime.execution_types" not in sys.modules
        _ = importlib.import_module("polysignal_lab.nautilus_runtime.strategies.base")

        assert "polysignal_lab.nautilus_runtime.execution" not in sys.modules
    finally:
        for name in tuple(sys.modules):
            if name.startswith("polysignal_lab.nautilus_runtime"):
                _ = sys.modules.pop(name, None)
        sys.modules.update(saved_runtime_modules)
        package = sys.modules.get("polysignal_lab.nautilus_runtime")
        if package is not None:
            for child in ("node", "strategies", "execution", "execution_types"):
                full_name = f"polysignal_lab.nautilus_runtime.{child}"
                if full_name in saved_runtime_modules:
                    setattr(package, child, saved_runtime_modules[full_name])
                elif hasattr(package, child):
                    delattr(package, child)
        if missing_runtime_attr:
            if hasattr(root_pkg, "nautilus_runtime"):
                delattr(root_pkg, "nautilus_runtime")
        else:
            setattr(root_pkg, "nautilus_runtime", saved_runtime_attr)


def test_nautilus_extra_is_optional_and_polymarket_scoped() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = cast(list[str], data["project"]["dependencies"])
    assert all("nautilus_trader" not in dep for dep in dependencies)
    nautilus_extra = cast(list[str], data["project"]["optional-dependencies"]["nautilus"])

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
    assert findings == []


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
    default_paths = (
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
        Path("src/polysignal_lab/nautilus_runtime/native_order.py"),
        Path("src/polysignal_lab/nautilus_runtime/native_strategy.py"),
        Path("src/polysignal_lab/nautilus_runtime/trading_node.py"),
        Path("src/polysignal_lab/nautilus_runtime/cache_reader.py"),
        Path("src/polysignal_lab/nautilus_runtime/projections.py"),
        Path("src/polysignal_lab/nautilus_runtime/observability.py"),
    )
    findings: list[str] = []
    for path in default_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []

def test_default_nautilus_entry_and_report_paths_do_not_reference_legacy_runtime_layers() -> None:
    forbidden = (
        "polysignal_lab.nautilus_runtime.matching",
        "polysignal_lab.nautilus_runtime.orchestrator",
        "polysignal_lab.nautilus_runtime.strategies.base",
        "polysignal_lab.nautilus_runtime.execution_types",
        "PaperWallet",
        "PaperExecutionResult",
    )
    default_paths = (
        Path("src/polysignal_lab/app/main.py"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
        Path("src/polysignal_lab/app/scheduler_reporting.py"),
    )
    findings: list[str] = []
    for path in default_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_runtime_duplicate_platform_modules_are_deleted() -> None:
    duplicate_modules = (
        Path("src/polysignal_lab/nautilus_runtime/matching.py"),
        Path("src/polysignal_lab/nautilus_runtime/orchestrator.py"),
        Path("src/polysignal_lab/nautilus_runtime/data_ingestor.py"),
        Path("src/polysignal_lab/nautilus_runtime/execution_types.py"),
        Path("src/polysignal_lab/nautilus_runtime/scheduler_compat.py"),
        Path("src/polysignal_lab/nautilus_runtime/position_policy.py"),
        Path("src/polysignal_lab/nautilus_runtime/settlement.py"),
        Path("src/polysignal_lab/nautilus_runtime/book_data.py"),
        Path("src/polysignal_lab/nautilus_runtime/patch_nautilus_polymarket_autoload.py"),
    )

    assert [str(path) for path in duplicate_modules if path.exists()] == []


def test_nautilus_runtime_source_has_no_platform_truth_source_terms() -> None:
    forbidden = (
        "NautilusMatchingPaperExecutionClient",
        "OwnedNautilusMatchingBoundary",
        "PaperWallet",
        "PaperExecutionResult",
        "PaperSettlementEngine",
        "PaperSimulator",
        "NautilusOrchestrator",
        "NautilusDataIngestor",
        "evaluate_all_conditions(",
        "matching_boundary",
        "process_resting_orders",
        "drain_events",
        "cache.add_order",
        "MessageBus(",
        "SimulatedExchange(",
        "BacktestExecClient(",
    )
    allowed_files = {
        Path("src/polysignal_lab/nautilus_runtime/cache_reader.py"),
        Path("src/polysignal_lab/nautilus_runtime/projections.py"),
    }
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_runtime_does_not_mirror_market_data_outside_nautilus_cache() -> None:
    forbidden_by_file = {
        Path("src/polysignal_lab/nautilus_runtime/node.py"): (
            "NautilusBookDataProvider",
            "book_data_provider =",
        ),
        Path("src/polysignal_lab/nautilus_runtime/native_strategy.py"): (
            ".update_book(",
            "update_book",
            ".update_trade(",
            "update_trade",
            "_domain_order_book(",
        ),
        Path("src/polysignal_lab/nautilus_bridge/market_view_assembler.py"): (
            "self._books",
            "self._trades",
            "update_book(",
            "update_trade(",
        ),
    }
    findings: list[str] = []
    for path, forbidden in forbidden_by_file.items():
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_runtime_does_not_patch_nautilus_installed_sources() -> None:
    forbidden = (
        "patch_nautilus_polymarket_autoload",
        "patch_source(",
        "EXPECTED_VERSION",
        "_handle_queue_exception",
        "_polysignal_precision_guard",
        "_install_polymarket_precision_runtime_guards",
        "_polymarket_precision_guarded_queue_exception_handler",
    )
    scanned_paths = (
        Path("Dockerfile"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_runtime_does_not_construct_instruments_locally() -> None:
    forbidden = (
        "class NautilusInstrumentMeta",
        "def instrument_id_for_token",
        "def build_binary_option",
        "BinaryOption(",
        "cache.add_instrument",
        "exchange.add_instrument",
        "DEFAULT_VENUE = \"POLYSIGNAL_PM_PAPER\"",
        "return f\"{condition}-{token}.POLYMARKET\"",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_observability_has_no_paper_model_recording_api() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/observability.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "from polysignal_lab.domain.paper_order import",
        "from polysignal_lab.domain.paper_position import",
        "from polysignal_lab.domain.paper_result import",
        "def record_order(",
        "def record_fill(",
        "def record_position(",
        "def record_settlement(",
        "def record_signal_from_order(",
        "def signal_candidate_from_order(",
        "PaperFillNotifier",
        "PaperFillMirror",
        "mirror_nautilus_paper_fill",
    )

    assert [token for token in forbidden if token in source] == []


def test_default_runtime_uses_livenode_builder_not_legacy_trading_node() -> None:
    forbidden = (
        "nautilus_trader.live.node",
        "TradingNodeConfig",
        "TradingNode(",
        "TradingNode =",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
        Path("src/polysignal_lab/nautilus_runtime/trading_node.py"),
        Path("src/polysignal_lab/nautilus_runtime/live_node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
def test_default_runtime_has_no_dynamic_runtime_class_factories() -> None:
    forbidden = (
        "new_class(",
        "runtime_native_strategy_type",
        "runtime_sidecar_actor_type",
        "runtime_market_rotation_actor_type",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_runtime/native_strategy.py"),
        Path("src/polysignal_lab/nautilus_runtime/sidecar_data.py"),
        Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []

@pytest.mark.xfail(strict=True, reason="Task 4 removes shared external sidecar state")
def test_default_runtime_has_no_shared_external_sidecar_store() -> None:
    forbidden_paths = (
        Path("src/polysignal_lab/nautilus_bridge/external_data.py"),
    )
    forbidden_tokens = (
        "ExternalDataSidecar",
        "update_spot(",
        "update_price_to_beat(",
        "self.sidecar",
    )
    scanned_roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/nautilus_bridge"),
    )
    path_findings = [str(path) for path in forbidden_paths if path.exists()]
    token_findings: list[str] = []
    for root in scanned_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            token_findings.extend(f"{path}:{token}" for token in forbidden_tokens if token in text)

    assert path_findings == []
    assert token_findings == []

@pytest.mark.xfail(strict=True, reason="Task 5 removes reverse instrument registry")
def test_market_catalog_has_no_reverse_instrument_truth_source() -> None:
    forbidden = (
        "_by_instrument",
        "by_instrument(",
        "condition_id_for_instrument(",
        "token_id_for_instrument(",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_bridge/market_registry.py"),
        Path("src/polysignal_lab/nautilus_bridge/market_catalog.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
@pytest.mark.xfail(strict=True, reason="Task 6 removes bare asyncio actor scheduling fallbacks")
def test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks() -> None:
    forbidden_by_file = {
        Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"): (
            "asyncio.create_task(",
            "asyncio.sleep(",
            "asyncio.new_event_loop(",
            "asyncio.run(",
            "asyncio.to_thread(",
        ),
        Path("src/polysignal_lab/nautilus_runtime/sidecar_data.py"): (
            "asyncio.create_task(",
            "asyncio.sleep(",
            "asyncio.new_event_loop(",
            "asyncio.run(",
            "asyncio.to_thread(",
        ),
    }
    findings: list[str] = []
    for path, forbidden in forbidden_by_file.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
@pytest.mark.xfail(strict=True, reason="Task 7 splits large Nautilus runtime functions")
def test_large_nautilus_runtime_functions_stay_under_limit() -> None:
    import ast

    roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/nautilus_bridge"),
    )
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno is None:
                        continue
                    line_count = node.end_lineno - node.lineno + 1
                    if line_count > 45:
                        findings.append(f"{path}:{node.lineno}-{node.end_lineno}:{node.name}:{line_count}")

    assert findings == []
