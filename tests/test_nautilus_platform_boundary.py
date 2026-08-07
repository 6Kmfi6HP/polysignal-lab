from __future__ import annotations

import ast
import importlib
import json
import re
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
    manifest = json.loads(
        Path("docs/runtime_verification/nautilus-polysignal-wheel.json").read_text()
    )

    dependencies = cast(list[str], data["project"]["dependencies"])
    expected = next(
        dependency
        for dependency in dependencies
        if dependency.startswith("nautilus_trader[polymarket] @ ")
    )
    assert f"#sha256={manifest['wheel_sha256']}" in expected
    nautilus_extra = cast(
        list[str], data["project"]["optional-dependencies"]["nautilus"]
    )

    assert nautilus_extra == [
        expected,
    ]
    assert data["project"]["requires-python"] == ">=3.12,<3.13"


def test_nautilus_dependency_avoids_ephemeral_develop_wheel() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    project = data["project"]
    dependencies = cast(list[str], project["dependencies"])
    nautilus_extra = cast(list[str], project["optional-dependencies"]["nautilus"])

    nautilus_dependencies = [
        dependency
        for dependency in [*dependencies, *nautilus_extra]
        if dependency.startswith("nautilus_trader[")
    ]
    nautilus_packages = [
        package for package in lock["package"] if package["name"] == "nautilus-trader"
    ]

    assert len(nautilus_dependencies) == 2
    assert all(".dev" not in dependency for dependency in nautilus_dependencies)
    assert len(nautilus_packages) == 1
    assert ".dev" not in nautilus_packages[0]["version"]


def test_nautilus_docker_and_lock_avoid_git_source_builds() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    lock_text = Path("uv.lock").read_text(encoding="utf-8")

    assert "git+https://github.com/nautechsystems/nautilus_trader" not in dockerfile
    assert (
        'source = { git = "https://github.com/nautechsystems/nautilus_trader'
        not in lock_text
    )


def test_cli_exposes_nautilus_mode_and_script() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert {"nautilus", "sandbox", "live", "backtest"}.issubset(app_main.MODE_VALUES)
    assert (
        pyproject["project"]["scripts"]["polysignal-nautilus"]
        == "polysignal_lab.nautilus_runtime.node:main"
    )


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
    scanned_roots = [Path("src/polysignal_lab/nautilus_runtime")]
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
                findings.extend(
                    f"{path}:{token}" for token in live_only if token in text
                )
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


def test_default_nautilus_entry_and_report_paths_do_not_reference_legacy_runtime_layers() -> (
    None
):
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
        Path("src/polysignal_lab/app/daily_report/__init__.py"),
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
        Path(
            "src/polysignal_lab/nautilus_runtime/patch_nautilus_polymarket_autoload.py"
        ),
        Path("src/polysignal_lab/nautilus_runtime/decision_policy_actor.py"),
        Path("src/polysignal_lab/nautilus_runtime/decision_messages.py"),
    )

    assert [str(path) for path in duplicate_modules if path.exists()] == []


def test_nautilus_runtime_has_single_managed_rtds_entrypoint() -> None:
    runtime_root = Path("src/polysignal_lab/nautilus_runtime")
    deleted_modules = (
        runtime_root / "spot_data_client.py",
        runtime_root / "spot_data_client" / "__init__.py",
    )
    forbidden_identifiers = {
        "PolySignalSpotData",
        "PolymarketRtdsSpotDataClient",
        "POLYSIGNAL_SPOT",
    }
    findings = [str(path) for path in deleted_modules if path.exists()]

    for path in runtime_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if (
                        alias.name == "websockets"
                        or "spot_data_client" in alias.name.split(".")
                    ):
                        findings.append(f"{path}:{node.lineno}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "websockets" or module.startswith("websockets."):
                    findings.append(f"{path}:{node.lineno}:import:{module}")
                if "spot_data_client" in module.split("."):
                    findings.append(f"{path}:{node.lineno}:import:{module}")
            elif isinstance(node, (ast.Name, ast.Attribute)):
                identifier = node.id if isinstance(node, ast.Name) else node.attr
                if identifier in forbidden_identifiers:
                    findings.append(f"{path}:{node.lineno}:identifier:{identifier}")
            elif isinstance(node, ast.Constant) and node.value == "POLYSIGNAL_SPOT":
                findings.append(f"{path}:{node.lineno}:literal:POLYSIGNAL_SPOT")

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    direct_dependencies = cast(list[str], pyproject["project"]["dependencies"])
    findings.extend(
        f"pyproject.toml:direct-dependency:{dependency}"
        for dependency in direct_dependencies
        if re.split(r"[\s\[<>=!~;@]", dependency, maxsplit=1)[0].lower() == "websockets"
    )

    assert findings == []


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
        Path("src/polysignal_lab/nautilus_runtime/market_view_assembler.py"): (
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
        'DEFAULT_VENUE = "POLYSIGNAL_PM_PAPER"',
        'return f"{condition}-{token}.POLYMARKET"',
    )
    findings: list[str] = []
    runtime_root = Path("src/polysignal_lab/nautilus_runtime")
    # MarketCatalog delegates identifier creation to the official Polymarket adapter;
    # it does not construct or cache Nautilus instruments locally.
    for path in runtime_root.rglob("*.py"):
        if path.name == "market_catalog.py":
            continue
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
        path.read_text(encoding="utf-8") for path in scanned_paths if path.exists()
    )

    assert [token for token in required if token not in source] == []
    assert [token for token in forbidden if token in source] == []


def test_default_runtime_has_no_dynamic_runtime_class_factories() -> None:
    forbidden = (
        "new_class(",
        "runtime_native_strategy_type",
        "runtime_market_rotation_actor_type",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_runtime/native_strategy.py"),
        Path("src/polysignal_lab/nautilus_runtime/custom_data_publisher.py"),
        Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_default_runtime_has_no_shared_external_data_store() -> None:
    forbidden_paths = (Path("src/polysignal_lab/nautilus_runtime/external_data.py"),)
    forbidden_tokens = (
        "update_spot(",
        "update_price_to_beat(",
    )
    scanned_roots = (Path("src/polysignal_lab/nautilus_runtime"),)
    path_findings = [str(path) for path in forbidden_paths if path.exists()]
    token_findings: list[str] = []
    for root in scanned_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            token_findings.extend(
                f"{path}:{token}" for token in forbidden_tokens if token in text
            )

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
        Path("src/polysignal_lab/nautilus_runtime/market_registry.py"),
        Path("src/polysignal_lab/nautilus_runtime/market_catalog.py"),
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
        Path("src/polysignal_lab/nautilus_runtime/custom_data_publisher.py"): (
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
        "from polysignal_lab.data.registries import OrderBookRegistry",
        "OrderBookRegistry()",
        "from polysignal_lab.data.polymarket_clob_ws import",
        "from polysignal_lab.data.polymarket_clob_rest import",
        "EmptyBookDataProvider",
    )
    roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/pretrade"),
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
        "from polysignal_lab.data.registries import OrderBookRegistry",
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
        "DecisionPolicyActor",
        "DecisionCandidateData",
        "DecisionResultData",
        "decision_policy_actor",
        "decision_messages",
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
        "PolymarketRtdsSpotDataClient",
        "POLYSIGNAL_SPOT",
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
            if "nautilus_runtime" in path.parts:
                findings.extend(
                    f"{path}:{token}" for token in wall_clock_tokens if token in text
                )
    assert findings == []


def test_custom_data_registration_requires_real_arrow_codecs() -> None:
    scanned = (Path("src/polysignal_lab/nautilus_runtime/custom_data_types.py"),)
    forbidden = (
        "pa.schema([])",
        "_ARROW_REGISTRATION_SCHEMA",
        "_unsupported_arrow",
        "Arrow serialization is unsupported",
    )
    findings: list[str] = []
    for path in scanned:
        source = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in source)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Data" for base in node.bases
            ):
                assignments = {
                    target.id
                    for item in node.body
                    if isinstance(item, (ast.Assign, ast.AnnAssign))
                    for target in (
                        item.targets if isinstance(item, ast.Assign) else [item.target]
                    )
                    if isinstance(target, ast.Name)
                }
                required = {
                    "_schema",
                    "to_arrow",
                    "from_arrow",
                    "encode_record_batch_py",
                    "decode_record_batch_py",
                }
                findings.extend(
                    f"{path}:{node.name}:missing:{name}"
                    for name in sorted(required - assignments)
                )
    assert findings == []


def test_nautilus_runtime_has_no_decision_policy_actor_bus() -> None:
    forbidden = (
        "DecisionCandidateData",
        "DecisionResultData",
        "DecisionPolicyActor",
        "decision_policy_actor",
        "decision_messages",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)
    assert findings == []


def test_strategy_owns_decision_policy_not_separate_actor() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/native_strategy.py").read_text(
        encoding="utf-8"
    )
    host_init = Path(
        "src/polysignal_lab/nautilus_runtime/strategy/host_init.py"
    ).read_text(encoding="utf-8")
    # Policy is Strategy-owned DI (bound in host_init), not a separate Actor bus.
    assert "strategy.policy =" in host_init or "self.policy =" in source
    assert "_apply_decision_batch" in source
    assert "DecisionCandidateData" not in source
    assert "DecisionCandidate" not in source
    registration = Path(
        "src/polysignal_lab/nautilus_runtime/runtime_registration.py"
    ).read_text(encoding="utf-8")
    assert "DecisionPolicyActor" not in registration


def test_native_strategy_does_not_expose_framework_owned_setters() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/native_strategy.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "@cache.setter",
        "@order_factory.setter",
        "def cache(self, value",
        "def order_factory(self, value",
    )

    assert [token for token in forbidden if token in source] == []


def test_signal_gate_commit_does_not_call_channel_rate_limiter() -> None:
    source = Path("src/polysignal_lab/pretrade/gate.py").read_text(encoding="utf-8")
    commit_start = source.index("def commit(")
    commit_end = source.index("\n    def ", commit_start + 1)
    commit_body = source[commit_start:commit_end]
    assert "rate_limiter" not in commit_body
    assert "CHANNEL_RATE_LIMIT" not in commit_body


def test_live_node_component_state_is_not_hard_disabled() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/live_node.py").read_text(
        encoding="utf-8"
    )
    forbidden = ("with_load_state(False)", "with_save_state(False)")
    required = ("with_load_state(True)", "with_save_state(True)")

    assert [token for token in forbidden if token in source] == []
    assert [token for token in required if token not in source] == []


def test_tester_contracts_do_not_restore_false_unavailable_premise() -> None:
    source = Path("tests/test_nautilus_runtime_contracts.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "test_datatester_exectester_pyo3_matrix_unavailable",
        "DataTester unavailable",
        "ExecTester unavailable",
    )
    required = (
        "test_datatester_is_constructible_with_polymarket_data_contract",
        "test_exectester_is_constructible_with_safe_local_contract",
        "test_tester_importable_registration_reports_native_type_boundary",
    )

    assert [token for token in forbidden if token in source] == []
    assert [token for token in required if token not in source] == []


def test_deleted_precision_and_local_venue_io_modules_stay_deleted() -> None:
    runtime_root = Path("src/polysignal_lab/nautilus_runtime")
    deleted = (
        runtime_root / "market_data_precision.py",
        runtime_root / "sandbox_precision_client.py",
        runtime_root / "spot_data_client.py",
    )
    forbidden = (
        "market_data_precision",
        "sandbox_precision_client",
        "spot_data_client",
        "normalize_market_data_to_instrument",
        "PolymarketRtdsSpotDataClient",
    )
    findings = [str(path) for path in deleted if path.exists()]
    for path in runtime_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in source)
    assert findings == []


def test_runtime_has_no_local_order_position_or_fill_truth() -> None:
    runtime_root = Path("src/polysignal_lab/nautilus_runtime")
    forbidden = (
        "class LocalOrderStore",
        "class LocalPositionStore",
        "class LocalFillStore",
        "self._orders =",
        "self._positions =",
        "self._fills =",
        "cache.add_order",
        "cache.add_position",
    )
    findings: list[str] = []
    for path in runtime_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in source)
    assert findings == []


def test_local_settlement_configuration_is_deleted() -> None:
    assert "settlement:" not in Path("config/signal_bot.yaml").read_text(
        encoding="utf-8"
    )
    assert "settlement:" not in Path("config/signal_bot.lab.yaml").read_text(
        encoding="utf-8"
    )


def test_default_cli_docker_compose_are_livenode_only() -> None:
    main_src = Path("src/polysignal_lab/app/main.py").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'NAUTILUS = "nautilus"' in main_src
    assert "MODE_VALUES" in main_src
    assert '"scheduler"' not in main_src
    assert "SCHEDULER" not in main_src
    assert 'CMD ["nautilus"]' in dockerfile or "CMD ['nautilus']" in dockerfile
    assert "LiveNode" in dockerfile
    assert 'command: ["nautilus"]' in compose
    assert "TradingNode" not in dockerfile
    assert "TradingNode" not in compose


def test_large_nautilus_runtime_functions_stay_under_limit() -> None:
    import ast

    roots = (Path("src/polysignal_lab/nautilus_runtime"),)
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


def test_reporting_package_stays_free_of_io_dependencies() -> None:
    """`reporting/` is pure computation; the I/O pipeline lives in `app/daily_report/`."""
    forbidden_prefixes = (
        "polysignal_lab.app",
        "polysignal_lab.dashboard",
        "polysignal_lab.nautilus_runtime",
        "polysignal_lab.publish",
        "polysignal_lab.storage",
    )
    findings: list[str] = []
    for path in sorted(Path("src/polysignal_lab/reporting").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.startswith(forbidden_prefixes):
                findings.append(f"{path}:{node.lineno}:{node.module}")

    assert findings == []
