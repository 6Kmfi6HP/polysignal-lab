from pathlib import Path

manual = Path(".omo/ulw-loop/evidence/paper-blockers-manual-qa.txt").read_text(
    encoding="utf-8"
)
focused = Path(".omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt").read_text(
    encoding="utf-8"
)

required = {
    "parseable repair result": "repair_parse=pass",
    "incomplete position skip": "repair_incomplete_position=pass",
    "incomplete cache guard": "cache_guard=pass",
    "SPLIT daily report counting": "split_report=pass",
    "malformed persisted rows filtered": "malformed_persisted_rows=pass",
}

for label, marker in required.items():
    ok = marker in manual
    print(f"{label}: {'pass' if ok else 'fail'} marker={marker}")
    if not ok:
        raise SystemExit(f"missing marker: {marker}")

if "46 passed" not in focused:
    raise SystemExit("focused pytest artifact missing 46 passed")

print("focused_tests: pass marker=46 passed")
print("focused_blocker_validation=pass")
