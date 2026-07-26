"""
Input: __future__, __future__.annotations, argparse, ast, pathlib, pathlib.Path, typing, typing.Final
Output: blocked_symbols, scan, skip_path, main
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Final


SCANNED_SUFFIXES: Final = {".py", ".yaml", ".yml", ".toml"}
SKIP_FILE_NAMES: Final = {
    ".env",
    "PRD.md",
    "refined_results.json",
    "safety.py",
    "scan_results.json",
    "test_safety.py",
}
SKIP_DIR_NAMES: Final = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".worktrees",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
NAUTILUS_RUNTIME_ALLOWED_SYMBOLS: Final = {"submit_order"}

SKIP_TOP_LEVEL_DIRS: Final = {"data", "logs", "refs", "state"}

LEGACY_TRADING_ISOLATION_SYMBOLS: Final = (
    "from polysignal_lab.paper.order_intent_executor import",
    "BestAsk" + "TakerExecutor",
    "Passive" + "GtdExecutor",
    "Paper" + "Simulator",
    "from polysignal_lab.paper." + "wallet import",
    "Paper" + "Wallet(",
    "BestAsk" + "TakerFillModel",
    "Paper" + "ExecutionPreflight",
    "Paper" + "ExitEngine",
    "Paper" + "SettlementEngine(self.wallet)",
    "Paper" + "FillNotifier",
    "Paper" + "FillMirror",
    "from polysignal_lab.domain.paper_" + "order import",
    "from polysignal_lab.domain.paper_" + "position import",
    "scheduler." + "wallet",
    "scheduler." + "paper",
    "paper_portfolio.process_signal",
    "paper_portfolio.tick_resting_orders",
    "shadow_" + "wallet",
    "new_class(",
    "runtime_native_strategy_type",
    "runtime_market_rotation_actor_type",
    "_by_instrument",
    "condition_id_for_instrument",
    "token_id_for_instrument",
)
# Dual-path residue that must not re-enter live runtime / decision / trading wiring.
LEGACY_DUAL_PATH_SYMBOLS: Final = (
    "from polysignal_lab.data.state import " + "OrderBookRegistry",
    "from polysignal_lab.data.state import " + "OrderBookRegistry,",
    "OrderBook" + "Registry()",
    "from polysignal_lab.data.polymarket_clob_ws import",
    "from polysignal_lab.data.polymarket_clob_rest import",
    "from polysignal_lab.data.binance_" + "spot_ws import",
    "EmptyBookDataProvider",
    "Trading" + "NodeConfig",
    "Trading" + "Node(",
    "from nautilus_trader.live.node import Trading" + "Node",
    "Decision" + "PolicyActor",
    "Nautilus" + "Decision" + "PolicyActor",
    "from polysignal_lab.nautilus_" + "bridge",
    "import polysignal_lab.nautilus_" + "bridge",
    "Matching" + "Engine(",
)
ACTOR_SCHEDULING_FALLBACK_SYMBOLS: Final = ("asyncio.create_task(",)
ACTOR_SCHEDULING_FALLBACK_PATHS: Final = {
    Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"),
    Path("src/polysignal_lab/nautilus_runtime/custom_data_publisher.py"),
}


def blocked_symbols() -> list[str]:
    return [
        "Secure" + "Client",
        "Async" + "Secure" + "Client",
        "Clob" + "Client(",
        "create_" + "order",
        "post_" + "order",
        "submit_" + "order",
        "cancel_" + "order",
        "cancel_" + "all",
        "redeem_" + "positions",
    ]


def scan(root: str | Path) -> list[tuple[str, str]]:
    base = Path(root)
    base_is_file = base.is_file()
    paths = (base,) if base_is_file else base.rglob("*")
    findings: list[tuple[str, str]] = []
    for path in paths:
        if path.is_dir() or skip_path(base, path):
            continue
        if path.suffix not in SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        report_path = path.name if base_is_file else path.relative_to(base).as_posix()
        symbols = list(blocked_symbols())
        if _is_project_source(path):
            symbols.extend(LEGACY_TRADING_ISOLATION_SYMBOLS)
        if _is_actor_scheduling_fallback_path(base, path):
            symbols.extend(ACTOR_SCHEDULING_FALLBACK_SYMBOLS)
        if _is_legacy_dual_path_guarded(base, path):
            symbols.extend(LEGACY_DUAL_PATH_SYMBOLS)
        for symbol in symbols:
            if symbol in text:
                if _is_submit_order_allowed_for_nautilus_strategy(path) and symbol == "submit_order":
                    continue
                findings.append((report_path, symbol))
        if _is_legacy_dual_path_guarded(base, path):
            for symbol in _legacy_dual_path_imports(text):
                finding = (report_path, symbol)
                if finding not in findings:
                    findings.append(finding)
    return findings


def skip_path(base: Path, path: Path) -> bool:
    rel = path.relative_to(base)
    if rel.parts == ("tests", "fixtures", "forbidden_polymarket_sdk_import.py"):
        return True
    if len(rel.parts) >= 2 and rel.parts[:2] == (".claude", "worktrees"):
        return True
    if path.name in SKIP_FILE_NAMES or path.name.startswith(".env."):
        return True
    if path.suffix in {".sqlite", ".sqlite3", ".pyc"}:
        return True
    if rel.parts and rel.parts[0] in SKIP_TOP_LEVEL_DIRS:
        return True
    return any(part in SKIP_DIR_NAMES or part.endswith(".egg-info") for part in rel.parts)


def _is_project_source(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    parts = path.parts
    for idx, part in enumerate(parts[:-1]):
        if part == "polysignal_lab" and "tests" not in parts[:idx]:
            return True
    return False


def _is_actor_scheduling_fallback_path(base: Path, path: Path) -> bool:
    rel = path if base.is_file() else path.relative_to(base)
    rel_text = rel.as_posix()
    path_text = path.as_posix()
    return any(
        rel_text.endswith(target.as_posix()) or path_text.endswith(target.as_posix())
        for target in ACTOR_SCHEDULING_FALLBACK_PATHS
    )


def _is_legacy_dual_path_guarded(base: Path, path: Path) -> bool:
    """Guard runtime/decision/trading packages against legacy book/CLOB reattachment."""
    _ = base
    if path.suffix != ".py":
        return False
    return any(
        part in {"alpha", "nautilus_runtime", "nautilus_runtime", "signal_layer"}
        for part in path.parts
    )


def _legacy_dual_path_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            relative_prefix = "." * node.level
            import_module = f"{relative_prefix}{node.module}"
            state_module = (
                f"{relative_prefix}data.state"
                if node.level
                else "polysignal_lab.data.state"
            )
            data_module = (
                f"{relative_prefix}data"
                if node.level
                else "polysignal_lab.data"
            )
            clob_modules = {
                f"{relative_prefix}data.polymarket_clob_ws"
                if node.level
                else "polysignal_lab.data.polymarket_clob_ws",
                f"{relative_prefix}data.polymarket_clob_rest"
                if node.level
                else "polysignal_lab.data.polymarket_clob_rest",
            }
            # Split tokens so static forbid-list scans of this file stay clean.
            _bridge = "nautilus_" + "bridge"
            _book_reg = "OrderBook" + "Registry"
            _policy_actor = "Decision" + "PolicyActor"
            _policy_mod = "decision_" + "policy_actor"
            bridge_modules = {
                f"{relative_prefix}{_bridge}"
                if node.level
                else f"polysignal_lab.{_bridge}",
            }
            paper_modules_prefix = (
                f"{relative_prefix}paper"
                if node.level
                else "polysignal_lab.paper"
            )
            imported_names = {alias.name for alias in node.names}
            if import_module == state_module and (
                _book_reg in imported_names or "*" in imported_names
            ):
                symbol = "*" if "*" in imported_names else _book_reg
                findings.append(f"from {import_module} import {symbol}")
            elif import_module in clob_modules:
                findings.append(f"from {import_module} import")
            elif import_module in bridge_modules or import_module.startswith(
                f"{list(bridge_modules)[0]}."
            ):
                findings.append(f"from {import_module} import")
            elif import_module == paper_modules_prefix or import_module.startswith(
                f"{paper_modules_prefix}."
            ):
                findings.append(f"from {import_module} import")
            elif import_module == data_module:
                for name in ("state", "polymarket_clob_ws", "polymarket_clob_rest"):
                    if name in imported_names:
                        findings.append(f"from {import_module} import {name}")
                if _book_reg in imported_names or "*" in imported_names:
                    symbol = "*" if "*" in imported_names else _book_reg
                    findings.append(f"from {import_module} import {symbol}")
            elif _policy_actor in imported_names or import_module.endswith(_policy_mod):
                findings.append(f"from {import_module} import {_policy_actor}")
        elif isinstance(node, ast.Import):
            _bridge = "nautilus_" + "bridge"
            blocked_imports = {
                "polysignal_lab.data.state",
                "polysignal_lab.data.polymarket_clob_ws",
                "polysignal_lab.data.polymarket_clob_rest",
                f"polysignal_lab.{_bridge}",
            }
            for alias in node.names:
                if alias.name not in blocked_imports and not alias.name.startswith(
                    f"polysignal_lab.{_bridge}."
                ):
                    if not alias.name.startswith("polysignal_lab.paper"):
                        continue
                symbol = f"import {alias.name}"
                if alias.asname:
                    symbol += f" as {alias.asname}"
                findings.append(symbol)
    return findings



def _is_submit_order_allowed_for_nautilus_strategy(path: Path) -> bool:
    """submit_order is legitimate on Nautilus strategy and test objects."""
    if path.suffix != ".py":
        return False
    parts = path.parts
    for idx, part in enumerate(parts[:-1]):
        if part != "polysignal_lab":
            continue
        if idx + 1 < len(parts) and parts[idx + 1] == "nautilus_runtime":
            return True
    # Also allow test files matching the nautilus test pattern
    if len(parts) >= 2 and parts[-2] == "tests":
        name = parts[-1]
        if name.endswith(".py") and ("nautilus" in name or name.startswith("test_nautilus")):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    findings = scan(args.root)
    if findings:
        for path, symbol in findings:
            print(f"BLOCKED {symbol} in {path}")
        raise SystemExit(1)
    print("Safety scan passed")


if __name__ == "__main__":
    main()
