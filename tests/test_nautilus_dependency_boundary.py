"""
Input: __future__, __future__.annotations, importlib, subprocess, sys, tomllib, pathlib, pathlib.Path
Output: test_default_package_import_does_not_require_nautilus, test_alpha_package_import_does_not_require_nautilus, test_order_plan_dto_import_does_not_require_nautilus, test_nautilus_is_required_default_dependency, test_nautilus_node_does_not_import_legacy_trading_state
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_package_import_does_not_require_nautilus() -> None:
    module = importlib.import_module("polysignal_lab")

    assert module is not None


def test_alpha_package_import_does_not_require_nautilus() -> None:
    result = _run_python(
        "import importlib, sys; "
        "module = importlib.import_module('polysignal_lab.alpha'); "
        "print(module.__name__); "
        "print('nautilus_loaded', 'nautilus_trader' in sys.modules); "
        "print('has_spec', hasattr(module, 'OrderSubmissionPlan'))"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "polysignal_lab.alpha"
    assert "nautilus_loaded False" in result.stdout
    assert "has_spec False" in result.stdout


def test_order_plan_dto_import_does_not_require_nautilus() -> None:
    result = _run_python(
        "import sys; "
        "from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan; "
        "print(OrderSubmissionPlan.__name__); "
        "print('nautilus_loaded', 'nautilus_trader' in sys.modules)"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "OrderSubmissionPlan"
    assert "nautilus_loaded False" in result.stdout


def test_nautilus_is_required_default_dependency() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    default_deps = data["project"]["dependencies"]
    optional_deps = data["project"]["optional-dependencies"]

    expected = "nautilus_trader[polymarket]==1.231.0.dev20260716+16604"
    assert expected in default_deps
    assert optional_deps["nautilus"] == [
        expected
    ]
    assert data["project"]["requires-python"] == ">=3.12"

def test_nautilus_node_does_not_import_legacy_trading_state() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/node.py").read_text()

    assert "scheduler_compat" not in source
    assert "init_scheduler_paper_components" not in source
    assert "mirror_nautilus_fill_into_scheduler" not in source
    assert "paper_fill_mirror=lambda" not in source
