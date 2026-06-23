from __future__ import annotations

from polysignal_lab.observability.safety import scan


def test_safety_scan_project_source():
    findings = scan("src")
    assert findings == []
