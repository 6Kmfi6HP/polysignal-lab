"""
Input: __future__, __future__.annotations, importlib, sys, tomllib, pytest, pathlib, pathlib.Path, typing, typing.cast
Output: test_default_import_does_not_require_nautilus, test_nautilus_node_and_strategies_do_not_import_legacy_execution, test_nautilus_extra_is_optional_and_polymarket_scoped, test_nautilus_docker_and_lock_avoid_git_source_builds, test_cli_exposes_nautilus_mode_and_script, test_default_source_keeps_forbidden_live_symbols_out_of_runtime, test_default_nautilus_runtime_source_avoids_local_paper_executors, test_default_nautilus_runtime_does_not_use_custom_paper_truth_sources, test_default_nautilus_entry_and_report_paths_do_not_reference_legacy_runtime_layers, test_nautilus_runtime_duplicate_platform_modules_are_deleted
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

from polysignal_lab.app import main as app_main


def test_default_import_does_not_require_nautilus() -> None:
    assert importlib.import_module("polysignal_lab") is not None

def test_nautilus_node_and_strategies_do_not_import_legacy_execution() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib,sys;"
                "importlib.import_module('polysignal_lab.nautilus_runtime.node');"
                "print('polysignal_lab.nautilus_runtime.execution' in sys.modules)"
            ),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_nautilus_is_required_dependency_for_default_runtime() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = cast(list[str], data["project"]["dependencies"])
    expected = "nautilus_trader[polymarket]==1.231.0.dev20260716+16604"
    assert expected in dependencies
    nautilus_extra = cast(list[str], data["project"]["optional-dependencies"]["nautilus"])

    assert nautilus_extra == [
        expected,
    ]
    assert data["project"]["requires-python"] == ">=3.12"

def test_nautilus_docker_and_lock_avoid_git_source_builds() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    lock_text = Path("uv.lock").read_text(encoding="utf-8")

    assert "git+https://github.com/nautechsystems/nautilus_trader" not in dockerfile
    assert 'source = { git = "https://github.com/nautechsystems/nautilus_trader' not in lock_text


def test_cli_exposes_nautilus_mode_and_script() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert {"nautilus", "sandbox", "live", "backtest"}.issubset(app_main.MODE_VALUES)
    assert pyproject["project"]["scripts"]["polysignal-nautilus"] == "polysignal_lab.nautilus_runtime.node:main"


def test_default_source_keeps_forbidden_live_symbols_out_of_runtime() -> None:
    forbidden = (
        "PolymarketLiveExecClientFactory",
        "exec_clients",
        "set_allowances.py",
        "create_api_key.py",
    )
    live_only = (
        "PolymarketExecutionClientFactory",
        "POLYMARKET_PK",
        "POLYMARKET_FUNDER",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
        "add_exec_client",
    )
    scanned_roots = [Path("src/polysignal_lab/nautilus_runtime"), Path("src/polysignal_lab/nautilus_bridge")]
    findings: list[str] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            tokens = forbidden
            if path.name in {"live_node.py", "optional_imports.py"}:
                tokens = tuple(token for token in forbidden if token != "exec_clients")
            else:
                findings.extend(f"{path}:{token}" for token in live_only if token in text)
            findings.extend(f"{path}:{token}" for token in tokens if token in text)
    live_path = Path("src/polysignal_lab/nautilus_runtime/live_node.py")
    if live_path.exists():
        live_text = live_path.read_text(encoding="utf-8")
        findings.extend(
            f"{live_path}:{token}"
            for token in ("PolymarketLiveExecClientFactory",)
            if token in live_text
        )
    for path in Path("src/polysignal_lab").rglob("*.py"):
        if path == live_path:
            continue
        text = path.read_text(encoding="utf-8")
        if "PolymarketLiveExecClientFactory" in text:
            findings.append(f"{path}:PolymarketLiveExecClientFactory")
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
        "polysignal_lab.nautilus_runtime.execution_types",
        "PaperWallet",
        "PaperExecutionResult",
    )
    default_paths = (
        Path("src/polysignal_lab/app/main.py"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
        Path("src/polysignal_lab/app/reporting.py"),
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
        "from polysignal_lab.domain.reporting_result import",
        "def record_order(",
        "def record_fill(",
        "def record_position(",
        "def record_settlement(",
        "def record_signal_from_order(",
        "def signal_candidate_from_order(",
        "PaperFillNotifier",
        "PaperFillMirror",
        "mirror_nautilus_fill",
    )

    assert [token for token in forbidden if token in source] == []


def test_default_runtime_uses_live_node_builder_api() -> None:
    required = (
        "LiveNode",
        ".builder(",
        "add_data_client",
        "add_simulated_exec_client",
        "PolymarketDataClientFactory",
    )
    forbidden = (
        "TradingNodeConfig",
        "add_data_client_factory",
        "add_exec_client_factory",
        "PolymarketLiveExecClientFactory",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_runtime/live_node.py"),
        Path("src/polysignal_lab/nautilus_runtime/node_builder.py"),
        Path("src/polysignal_lab/nautilus_runtime/optional_imports.py"),
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in scanned_paths
        if path.exists()
    )

    assert [token for token in required if token not in source] == []
    assert [token for token in forbidden if token in source] == []


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

def test_runtime_decision_paths_block_legacy_orderbook_and_clob_reattachment() -> None:
    forbidden = (
        "from polysignal_lab.data.state import OrderBookRegistry",
        "OrderBookRegistry()",
        "from polysignal_lab.data.polymarket_clob_ws import",
        "from polysignal_lab.data.polymarket_clob_rest import",
        "EmptyBookDataProvider",
    )
    roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/nautilus_bridge"),
        Path("src/polysignal_lab/signal_layer"),
        Path("src/polysignal_lab/alpha"),
    )
    findings: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            findings.extend(f"{path}:{token}" for token in forbidden if token in text)
    assert findings == []


def test_legacy_v1_compatibility_modules_are_deleted() -> None:
    deleted = (
        Path("src/polysignal_lab/data/binance_spot_ws.py"),
        Path("src/polysignal_lab/data/LEGACY_DUAL_PATH.md"),
        Path("src/polysignal_lab/paper/event_projection.py"),
        Path("src/polysignal_lab/app/scheduler_reporting.py"),
        Path("src/polysignal_lab/app/scheduler_reporting_build.py"),
        Path("src/polysignal_lab/app/scheduler_reporting_equity.py"),
        Path("src/polysignal_lab/app/scheduler_reporting_sources.py"),
        Path("src/polysignal_lab/app/scheduler_reporting_storage.py"),
        Path("src/polysignal_lab/app/scheduler_reporting_types.py"),
        Path("src/polysignal_lab/nautilus_runtime/scheduler_compat.py"),
        Path("src/polysignal_lab/domain/snapshot.py"),
        Path("src/polysignal_lab/domain/snapshot_batch.py"),
        Path("src/polysignal_lab/data/market_snapshot.py"),
        Path("src/polysignal_lab/data/polymarket_clob_ws.py"),
        Path("src/polysignal_lab/data/polymarket_clob_rest.py"),
        Path("src/polysignal_lab/data/public_market_data_client.py"),
        Path("src/polysignal_lab/data/orderbook_payload.py"),
        Path("src/polysignal_lab/data/book_reconciliation.py"),
        Path("src/polysignal_lab/alpha/legacy_snapshot_adapter.py"),
        Path("src/polysignal_lab/domain/paper_report.py"),
        Path("src/polysignal_lab/domain/paper_result.py"),
        Path("src/polysignal_lab/nautilus_runtime/livenode_registration.py"),
        Path("src/polysignal_lab/nautilus_runtime/paper_risk.py"),
        Path("src/polysignal_lab/paper"),
    )
    assert [str(path) for path in deleted if path.exists()] == []


def test_reporting_runtime_uses_only_canonical_report_identifiers() -> None:
    migration = Path("src/polysignal_lab/storage/projection_migration.py")
    forbidden = (
        "paper_order_id",
        "paper_fill_id",
        "paper_position_id",
        "paper_trade_id",
        "projected_order_id",
        "projected_fill_id",
        "projected_position_id",
        "projected_result_id",
        "normalize_projected_",
        "query_projected_",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab").rglob("*.py"):
        if path == migration:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)
    assert findings == []


def test_final_v2_single_track_static_gates() -> None:
    """Final remove-legacy forbid-list for the LiveNode-only runtime.

    Intentional gaps (documented, not gated as failures):
    - Precision factory / DataTester-ExecTester pyo3 matrix: see
      tests/test_nautilus_runtime_contracts.py skips.
    - node_crash.py may use wall-clock timestamps for dump filenames only.
    """
    forbidden_tokens = (
        "TradingNodeConfig",
        "TradingNode(",
        "from nautilus_trader.live.node import TradingNode",
        "OrderBookRegistry()",
        "from polysignal_lab.data.state import OrderBookRegistry",
        "from polysignal_lab.data.binance_spot_ws import",
        "from polysignal_lab.app.scheduler_reporting",
        "from polysignal_lab.paper.event_projection import",
        "MessageBus(",
        "ExecutionEngine(",
        "Portfolio(",
        "SimulatedExchange(",
        "PolymarketLiveExecClientFactory",
        "PaperWallet(",
        "PaperSimulator",
        "BestAskTakerExecutor",
        "PassiveGtdExecutor",
        "def restore_orders(",
        "def restore_positions(",
        "def restore_fills(",
        "def restore_order_count(",
        "def restore_paper_positions(",
        "def restore_trading_state(",
        "class MarketSubscriptionCoordinator",
        "refresh_stale_market_subscription",
        "deferred_resubscribe_condition_ids",
        "stale_refresh_attempts_by_condition",
        "last_stale_refresh_at",
        "NautilusDecisionPolicyActor",
        "HedgeWorkflow",
        "hedge_workflows",
        "_entered_markets",
        "_sniped_markets",
        "_pre_ordered",
        "_reconciled",
        "_layer_intent",
        "_entry_price_intent",
        "_can_enter",
        "_pending_hedges",
        "_active_baskets",
        "_exit_inflight",
        "_exit_thresholds_for_instruments",
        "_submitted_levels",
        "_accepted_counts",
        "_last_entry_at",
        "_last_favorite",
        "_pending_signal_samples",
        "bind_signal(",
        "split_strategy_payload",
        "migrated_from_v1",
        "submitted_signal_keys",
        "submitted_orders",
        "reset_position(",
        "NautilusOrderSpec",
        "SpotTick = SpotPrice",
        "build_paper_live_node",
        "PaperLiveNode",
        "paper_trading",
        "register_polysignal_data_types",
        "call_subscription",
        "_subscription_method",
        "_resolve_subscribe_data",
        "PolymarketSettlementConfig",
    )
    wall_clock_tokens = (
        "datetime.now(",
        "time.time(",
    )
    # Crash dumps may stamp wall clock; not trading-decision time.
    wall_clock_allowed = {
        Path("src/polysignal_lab/nautilus_runtime/node_crash.py"),
    }
    scanned_roots = (Path("src/polysignal_lab"),)
    findings: list[str] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            findings.extend(
                f"{path}:{token}" for token in forbidden_tokens if token in text
            )
            if path in wall_clock_allowed:
                continue
            if "nautilus_runtime" in path.parts or "nautilus_bridge" in path.parts:
                findings.extend(
                    f"{path}:{token}"
                    for token in wall_clock_tokens
                    if token in text
                )
    assert findings == []


def test_local_settlement_configuration_is_deleted() -> None:
    assert "settlement:" not in Path("config/signal_bot.yaml").read_text(encoding="utf-8")
    assert "settlement:" not in Path("config/signal_bot.lab.yaml").read_text(encoding="utf-8")


def test_default_cli_docker_compose_are_livenode_only() -> None:
    main_src = Path("src/polysignal_lab/app/main.py").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'NAUTILUS = "nautilus"' in main_src
    assert "MODE_VALUES" in main_src
    assert '"scheduler"' not in main_src
    assert "SCHEDULER" not in main_src
    assert "CMD [\"nautilus\"]" in dockerfile or "CMD ['nautilus']" in dockerfile
    assert "LiveNode" in dockerfile
    assert 'command: ["nautilus"]' in compose
    assert "TradingNode" not in dockerfile
    assert "TradingNode" not in compose


def test_large_nautilus_runtime_functions_stay_under_limit() -> None:
    import ast

    roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/nautilus_bridge"),
    )
    findings: list[str] = []
    allowed_existing_boundaries = {
        "native_strategy_exit.py:_build_exit_decision",
        "native_strategy_exit.py:_decision_for_position",
        "native_strategy.py:__init__",
        "market_rotation.py:__init__",
        "order_events.py:_record_early_exit_result",
    }
    for root in roots:
        for path in root.rglob("*.py"):
            if path.name in ("__init__.py", "node_cli.py"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno is None:
                        continue
                    line_count = node.end_lineno - node.lineno + 1
                    if line_count > 49:
                        boundary = f"{path.name}:{node.name}"
                        if boundary not in allowed_existing_boundaries:
                            findings.append(
                                f"{path}:{node.lineno}-{node.end_lineno}:{node.name}:{line_count}"
                            )

    assert findings == []
