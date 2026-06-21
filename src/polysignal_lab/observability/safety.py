from __future__ import annotations

import argparse
from pathlib import Path


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
    findings: list[tuple[str, str]] = []
    skip_names = {"safety.py", "test_safety.py", "PRD.md"}
    for path in base.rglob("*"):
        if path.is_dir() or path.name in skip_names or ".pytest_cache" in path.parts or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".yaml", ".yml", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for symbol in blocked_symbols():
            if symbol in text:
                findings.append((str(path.relative_to(base)), symbol))
    return findings


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
