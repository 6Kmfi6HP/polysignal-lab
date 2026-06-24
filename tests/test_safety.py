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

def test_safety_scan_project_source():
    findings = scan("src")
    assert findings == []
