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
            if path == _ALLOWED_SDK_IMPORT_FILE:
                continue
            offenders.append(path)
    return offenders


def test_polymarket_sdk_imports_are_adapter_only() -> None:
    assert find_forbidden_sdk_imports([Path("src/polysignal_lab")]) == []


def test_forbidden_sdk_import_fixture_is_detected() -> None:
    fixture = Path("tests/fixtures/forbidden_polymarket_sdk_import.py")
    assert find_forbidden_sdk_imports([fixture]) == [fixture]



def test_safety_scan_ignores_deliberate_forbidden_fixture() -> None:
    findings = scan("tests/fixtures")
    assert findings == []

def test_safety_scan_project_source():
    findings = scan("src")
    assert findings == []
