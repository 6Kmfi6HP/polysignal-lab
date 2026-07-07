"""
Input: __future__, __future__.annotations, pathlib, pathlib.Path, polysignal_lab.observability.safety, polysignal_lab.observability.safety.scan
Output: find_forbidden_sdk_imports, test_polymarket_sdk_imports_are_adapter_only, test_polymarket_sdk_import_allowlist_accepts_absolute_adapter_path, test_forbidden_sdk_import_fixture_is_detected, test_safety_scan_reports_deliberate_forbidden_fixture_directory, test_safety_scan_reports_deliberate_forbidden_fixture_file, test_safety_scan_repo_root_exempts_only_deliberate_fixture_path, test_safety_scan_skips_agent_worktrees_but_not_source, test_safety_scan_checks_hidden_claude_dirs_outside_agent_worktrees, test_safety_scan_blocks_create_task_in_nautilus_actor_fallback_paths
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations
from pathlib import Path

from polysignal_lab.observability.safety import scan

_ALLOWED_SDK_IMPORT_FILE = Path("src/polysignal_lab/data/polymarket_clob_rest.py")


def find_forbidden_sdk_imports(paths: list[Path]) -> list[Path]:
    offenders: list[Path] = []
    for root in paths:
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "py_clob_client_v2" not in text:
                continue
            if path.resolve() == _ALLOWED_SDK_IMPORT_FILE.resolve():
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


def test_safety_scan_repo_root_exempts_only_deliberate_fixture_path(tmp_path: Path) -> None:
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
    offender.write_text("def make_client():\n    return ClobClient(host='x')\n", encoding="utf-8")

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
    offender.write_text("def make_client():\n    return ClobClient(host='x')\n", encoding="utf-8")

    assert scan(tmp_path) == [("src/forbidden_polymarket_sdk_import.py", "ClobClient(")]


def test_safety_scan_checks_hidden_claude_dirs_outside_agent_worktrees(
    tmp_path: Path,
) -> None:
    hidden_source = tmp_path / "src" / "polysignal_lab" / ".claude"
    hidden_source.mkdir(parents=True)
    offender = hidden_source / "forbidden.py"
    offender.write_text("def make_client():\n    return ClobClient(host='x')\n", encoding="utf-8")

    assert scan(tmp_path) == [
        ("src/polysignal_lab/.claude/forbidden.py", "ClobClient(")
    ]

def test_safety_scan_blocks_create_task_in_nautilus_actor_fallback_paths(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "src" / "polysignal_lab" / "nautilus_runtime"
    runtime_dir.mkdir(parents=True)
    market_rotation = runtime_dir / "market_rotation.py"
    sidecar_data = runtime_dir / "sidecar_data.py"
    node = runtime_dir / "node.py"
    market_rotation.write_text("import asyncio\nasyncio.create_task(job())\n", encoding="utf-8")
    sidecar_data.write_text("import asyncio\nasyncio.create_task(job())\n", encoding="utf-8")
    node.write_text("import asyncio\nasyncio.create_task(job())\n", encoding="utf-8")

    assert set(scan(tmp_path)) == {
        ("src/polysignal_lab/nautilus_runtime/market_rotation.py", "asyncio.create_task("),
        ("src/polysignal_lab/nautilus_runtime/sidecar_data.py", "asyncio.create_task("),
    }


def test_safety_scan_project_source():
    findings = scan("src")
    assert findings == []
