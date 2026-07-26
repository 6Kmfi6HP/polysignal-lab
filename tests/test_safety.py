from __future__ import annotations
from pathlib import Path

from polysignal_lab.observability.safety import scan


def find_forbidden_sdk_imports(paths: list[Path]) -> list[Path]:
    offenders: list[Path] = []
    for root in paths:
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "py_clob_client_v2" not in text:
                continue
            offenders.append(path)
    return offenders


def test_polymarket_sdk_imports_are_adapter_only() -> None:
    assert find_forbidden_sdk_imports([Path("src/polysignal_lab")]) == []


def test_polymarket_sdk_import_allowlist_accepts_absolute_adapter_path() -> None:
    assert find_forbidden_sdk_imports([Path("src/polysignal_lab").resolve()]) == []


def test_forbidden_sdk_import_fixture_is_detected() -> None:
    fixture = Path("tests/fixtures/forbidden_polymarket_sdk_import.py")
    assert find_forbidden_sdk_imports([fixture]) == [fixture]


def test_safety_scan_reports_deliberate_forbidden_fixture_directory() -> None:
    findings = scan("tests/fixtures")
    assert ("forbidden_polymarket_sdk_import.py", "ClobClient(") in findings


def test_safety_scan_reports_deliberate_forbidden_fixture_file() -> None:
    fixture = Path("tests/fixtures/forbidden_polymarket_sdk_import.py")
    assert scan(fixture) == [(fixture.name, "ClobClient(")]


def test_safety_scan_repo_root_exempts_only_deliberate_fixture_path(
    tmp_path: Path,
) -> None:
    fixture_dir = tmp_path / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    deliberate_fixture = fixture_dir / "forbidden_polymarket_sdk_import.py"
    deliberate_fixture.write_text(
        "def make_client():\n    return ClobClient(host='fixture')\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    offender = src / "forbidden_polymarket_sdk_import.py"
    offender.write_text(
        "def make_client():\n    return ClobClient(host='x')\n", encoding="utf-8"
    )

    assert scan(tmp_path) == [("src/forbidden_polymarket_sdk_import.py", "ClobClient(")]


def test_safety_scan_skips_agent_worktrees_but_not_source(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".claude" / "worktrees" / "wf" / "tests" / "fixtures"
    agent_dir.mkdir(parents=True)
    (agent_dir / "forbidden_polymarket_sdk_import.py").write_text(
        "def make_client():\n    return ClobClient(host='scratch')\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    offender = src / "forbidden_polymarket_sdk_import.py"
    offender.write_text(
        "def make_client():\n    return ClobClient(host='x')\n", encoding="utf-8"
    )

    assert scan(tmp_path) == [("src/forbidden_polymarket_sdk_import.py", "ClobClient(")]


def test_safety_scan_checks_hidden_claude_dirs_outside_agent_worktrees(
    tmp_path: Path,
) -> None:
    hidden_source = tmp_path / "src" / "polysignal_lab" / ".claude"
    hidden_source.mkdir(parents=True)
    offender = hidden_source / "forbidden.py"
    offender.write_text(
        "def make_client():\n    return ClobClient(host='x')\n", encoding="utf-8"
    )

    assert scan(tmp_path) == [
        ("src/polysignal_lab/.claude/forbidden.py", "ClobClient(")
    ]


def test_safety_scan_blocks_create_task_in_nautilus_actor_fallback_paths(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_dir.mkdir(parents=True)
    market_rotation = runtime_dir / "market_rotation.py"
    publisher_data = runtime_dir / "custom_data_publisher.py"
    node = runtime_dir / "node.py"
    market_rotation.write_text(
        "import asyncio\nasyncio.create_task(job())\n", encoding="utf-8"
    )
    publisher_data.write_text(
        "import asyncio\nasyncio.create_task(job())\n", encoding="utf-8"
    )
    node.write_text("import asyncio\nasyncio.create_task(job())\n", encoding="utf-8")

    assert set(scan(tmp_path)) == {
        (
            "src/polysignal_lab/nautilus_runtime/market_rotation.py",
            "asyncio.create_task(",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/custom_data_publisher.py",
            "asyncio.create_task(",
        ),
    }


def test_safety_scan_project_source():
    findings = scan("src")
    assert findings == []


def test_safety_scan_detects_aliased_legacy_imports_in_guarded_paths(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_dir.mkdir(parents=True)
    source = runtime_dir / "legacy_imports.py"
    source.write_text(
        "from polysignal_lab.data.registries import OrderBookRegistry\n"
        "from polysignal_lab.data.registries import (\n"
        "    OrderBookRegistry as LegacyRegistry,\n"
        ")\n"
        "import polysignal_lab.data.registries as legacy_state\n"
        "import polysignal_lab.data.polymarket_clob_ws as legacy_ws\n"
        "import polysignal_lab.data.polymarket_clob_rest as legacy_rest\n"
        "from polysignal_lab.data.polymarket_clob_ws import Client\n"
        "from polysignal_lab.data.polymarket_clob_rest import Client\n"
        "OrderBookRegistry()\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "from polysignal_lab.data.registries import OrderBookRegistry",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "OrderBookRegistry()",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "from polysignal_lab.data.polymarket_clob_ws import",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "from polysignal_lab.data.polymarket_clob_rest import",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "import polysignal_lab.data.registries as legacy_state",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "import polysignal_lab.data.polymarket_clob_ws as legacy_ws",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/legacy_imports.py",
            "import polysignal_lab.data.polymarket_clob_rest as legacy_rest",
        ),
    ]


def test_safety_scan_blocks_relative_legacy_imports_in_guarded_paths(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_dir.mkdir(parents=True)
    source = runtime_dir / "relative_legacy_imports.py"
    source.write_text(
        "from ..data.registries import MarketRegistry\n"
        "from ..data.registries import OrderBookRegistry\n"
        "from ...data.registries import *\n"
        "from ..data.polymarket_clob_ws import Client\n"
        "from ..data.polymarket_clob_rest import Client\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == [
        (
            "src/polysignal_lab/nautilus_runtime/relative_legacy_imports.py",
            "from ..data.registries import OrderBookRegistry",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/relative_legacy_imports.py",
            "from ...data.registries import *",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/relative_legacy_imports.py",
            "from ..data.polymarket_clob_ws import",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/relative_legacy_imports.py",
            "from ..data.polymarket_clob_rest import",
        ),
    ]


def test_safety_scan_blocks_decision_policy_actor_and_bridge_residue(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_dir.mkdir(parents=True)
    source = runtime_dir / "dual_path_residue.py"
    source.write_text(
        "from polysignal_lab.nautilus_bridge.policy import DecisionPolicyActor\n"
        "from polysignal_lab.nautilus_runtime.decision_policy_actor import X\n"
        "import polysignal_lab.nautilus_bridge as bridge\n"
        "class DecisionPolicyActor: ...\n"
        "MatchingEngine()\n",
        encoding="utf-8",
    )
    project_dir = tmp_path / "src" / "polysignal_lab" / "app"
    project_dir.mkdir(parents=True)
    project_source = project_dir / "paper_residue.py"
    project_source.write_text(
        "from polysignal_lab.domain.paper_order import PaperOrder\n"
        "PaperFillNotifier()\n"
        "shadow_wallet = {}\n",
        encoding="utf-8",
    )

    findings = set(scan(tmp_path))
    assert (
        "src/polysignal_lab/nautilus_runtime/dual_path_residue.py",
        "DecisionPolicyActor",
    ) in findings
    assert (
        "src/polysignal_lab/nautilus_runtime/dual_path_residue.py",
        "from polysignal_lab.nautilus_bridge",
    ) in findings or any(
        "nautilus_bridge" in symbol
        for path, symbol in findings
        if path.endswith("dual_path_residue.py")
    )
    assert (
        "src/polysignal_lab/nautilus_runtime/dual_path_residue.py",
        "MatchingEngine(",
    ) in findings
    assert (
        "src/polysignal_lab/app/paper_residue.py",
        "from polysignal_lab.domain.paper_order import",
    ) in findings
    assert (
        "src/polysignal_lab/app/paper_residue.py",
        "PaperFillNotifier",
    ) in findings
    assert (
        "src/polysignal_lab/app/paper_residue.py",
        "shadow_wallet",
    ) in findings


def test_safety_scan_blocks_package_legacy_imports_in_decision_paths(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_dir.mkdir(parents=True)
    runtime_source = runtime_dir / "package_legacy_imports.py"
    runtime_source.write_text(
        "from polysignal_lab.data.registries import *\n"
        "from ..data import registries\n"
        "from ..data import polymarket_clob_ws\n"
        "from polysignal_lab.data import polymarket_clob_rest as rest\n"
        "from polysignal_lab.data import OrderBookRegistry\n"
        "from ..data import *\n",
        encoding="utf-8",
    )
    alpha_dir = tmp_path / "src" / "polysignal_lab" / "alpha"
    alpha_dir.mkdir(parents=True)
    alpha_source = alpha_dir / "legacy_import.py"
    alpha_source.write_text(
        "from ..data import registries\n",
        encoding="utf-8",
    )

    assert set(scan(tmp_path)) == {
        (
            "src/polysignal_lab/nautilus_runtime/package_legacy_imports.py",
            "from polysignal_lab.data.registries import *",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/package_legacy_imports.py",
            "from ..data import registries",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/package_legacy_imports.py",
            "from ..data import polymarket_clob_ws",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/package_legacy_imports.py",
            "from polysignal_lab.data import polymarket_clob_rest",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/package_legacy_imports.py",
            "from polysignal_lab.data import OrderBookRegistry",
        ),
        (
            "src/polysignal_lab/nautilus_runtime/package_legacy_imports.py",
            "from ..data import *",
        ),
        (
            "src/polysignal_lab/alpha/legacy_import.py",
            "from ..data import registries",
        ),
    }
