"""
Input: __future__, __future__.annotations, ast, pathlib, pathlib.Path
Output: test_runtime_functions_stay_reviewable
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import ast
from pathlib import Path


LIMITS = {
    "src/polysignal_lab/nautilus_runtime/node.py": {
        "run_nautilus_cli": 70,
    },
    "src/polysignal_lab/nautilus_runtime/node_builder.py": {
        "build_live_node": 55,
    },
    "src/polysignal_lab/nautilus_runtime/node_cli.py": {
        "run_nautilus_cli_async": 70,
    },
    "src/polysignal_lab/app/scheduler_reporting.py": {
        "generate_daily_report": 80,
    },
}


def _function_lengths(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lengths: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno is not None:
            lengths[node.name] = node.end_lineno - node.lineno + 1
    return lengths


def test_runtime_functions_stay_reviewable() -> None:
    offenders: list[str] = []
    for path_text, limits in LIMITS.items():
        lengths = _function_lengths(Path(path_text))
        for name, limit in limits.items():
            actual = lengths[name]
            if actual > limit:
                offenders.append(f"{path_text}:{name}:{actual}>{limit}")

    assert offenders == []
