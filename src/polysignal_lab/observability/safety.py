from __future__ import annotations

import argparse
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
SKIP_TOP_LEVEL_DIRS: Final = {"data", "logs", "refs", "state"}

LOCAL_PAPER_ISOLATION_SYMBOLS: Final = (
    "from polysignal_lab.paper.order_intent_executor import",
    "BestAskTakerExecutor",
    "PassiveGtdExecutor",
    "PaperSimulator",
    "PolySignalPaperExecutionClient",
    "create_paper_execution_client",
)


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
        symbols = blocked_symbols()
        if _is_default_nautilus_runtime_source(path):
            symbols.extend(LOCAL_PAPER_ISOLATION_SYMBOLS)
        for symbol in symbols:
            if symbol in text:
                findings.append((report_path, symbol))
    return findings


def skip_path(base: Path, path: Path) -> bool:
    rel = path.relative_to(base)
    if rel.parts == ("tests", "fixtures", "forbidden_polymarket_sdk_import.py"):
        return True
    if path.name in SKIP_FILE_NAMES or path.name.startswith(".env."):
        return True
    if path.suffix in {".sqlite", ".sqlite3", ".pyc"}:
        return True
    if rel.parts and rel.parts[0] in SKIP_TOP_LEVEL_DIRS:
        return True
    return any(part in SKIP_DIR_NAMES or part.endswith(".egg-info") for part in rel.parts)


def _is_default_nautilus_runtime_source(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    parts = path.parts
    for idx, part in enumerate(parts[:-1]):
        if part != "polysignal_lab":
            continue
        if idx + 1 < len(parts) and parts[idx + 1] == "nautilus_runtime":
            return "tests" not in parts[:idx]
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
