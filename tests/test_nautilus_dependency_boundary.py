from __future__ import annotations

import importlib
import json
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

    expected = next(
        dependency
        for dependency in default_deps
        if dependency.startswith("nautilus_trader[polymarket] @ ")
    )
    assert "#sha256=400419cef770f6c0bab4732d6a84ab6e504aab7f49b158d08856e1c4decb0f9a" in expected
    assert expected in default_deps
    assert optional_deps["nautilus"] == [expected]
    assert data["project"]["requires-python"] == ">=3.12,<3.13"


def test_nautilus_wheel_provenance_is_consistent_across_build_inputs() -> None:
    manifest = json.loads(
        Path("docs/runtime_verification/nautilus-polysignal-wheel.json").read_text()
    )
    project = tomllib.loads(Path("pyproject.toml").read_text())
    dockerfile = Path("Dockerfile").read_text()
    dependencies = project["project"]["dependencies"]
    requirement = next(
        dependency
        for dependency in dependencies
        if dependency.startswith("nautilus_trader[polymarket] @ ")
    )

    assert manifest["release_tag"] in requirement
    assert manifest["wheel_filename"].replace("+", "%2B") in requirement
    assert f"#sha256={manifest['wheel_sha256']}" in requirement
    for key, label in (
        ("upstream_base_sha", "upstream-sha"),
        ("patch_commit_sha", "patch-sha"),
        ("version", "version"),
        ("wheel_sha256", "wheel-sha256"),
    ):
        assert f'io.polysignal.nautilus.{label}="{manifest[key]}"' in dockerfile
    assert "verify_nautilus_wheel_provenance.py" in manifest["build_command"]


def test_nautilus_node_does_not_import_legacy_trading_state() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/node.py").read_text()

    assert "scheduler_compat" not in source
    assert "init_scheduler_paper_components" not in source
    assert "mirror_nautilus_fill_into_scheduler" not in source
    assert "paper_fill_mirror=lambda" not in source
