"""
Input: __future__, __future__.annotations, argparse, ast, pathlib, pathlib.Path, typing, typing.Final
Output: blocked_symbols, scan, skip_path, _legacy_dual_path_imports, main
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

LOCAL_PAPER_ISOLATION_SYMBOLS: Final = (
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
    "scheduler." + "wallet",
    "scheduler." + "paper",
    "paper_portfolio.process_signal",
    "paper_portfolio.tick_resting_orders",
    "new_class(",
    "ExternalDataSidecar",
    "runtime_native_strategy_type",
    "runtime_sidecar_actor_type",
    "runtime_market_rotation_actor_type",
    "_by_instrument",
    "condition_id_for_instrument",
    "token_id_for_instrument",
)
# Dual-path residue that must not re-enter live runtime / decision / trading wiring.
LEGACY_DUAL_PATH_SYMBOLS: Final = (
    "from polysignal_lab.data.state import OrderBookRegistry",
    "from polysignal_lab.data.state import OrderBookRegistry,",
    "OrderBookRegistry()",
    "from polysignal_lab.data.polymarket_clob_ws import",
    "from polysignal_lab.data.polymarket_clob_rest import",
    "EmptyBookDataProvider",
)
ACTOR_SCHEDULING_FALLBACK_SYMBOLS: Final = ("asyncio.create_task(",)
ACTOR_SCHEDULING_FALLBACK_PATHS: Final = {
    Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"),
    Path("src/polysignal_lab/nautilus_runtime/sidecar_data.py"),
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
        report_path = path.name if base_is_file else str(path.relative_to(base))
        symbols = list(blocked_symbols())
        if _is_project_source(path):
            symbols.extend(LOCAL_PAPER_ISOLATION_SYMBOLS)
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
        part in {"nautilus_runtime", "nautilus_bridge", "signal_layer"}
        for part in path.parts
    )


def _legacy_dual_path_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    state_module = "polysignal_lab.data.state"
    clob_modules = {
        "polysignal_lab.data.polymarket_clob_ws",
        "polysignal_lab.data.polymarket_clob_rest",
    }
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == state_module and any(
                alias.name == "OrderBookRegistry" for alias in node.names
            ):
                findings.append(f"from {state_module} import OrderBookRegistry")
            elif node.module in clob_modules:
                findings.append(f"from {node.module} import")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in clob_modules | {state_module}:
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
