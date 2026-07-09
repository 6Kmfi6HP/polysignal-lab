from pathlib import Path

checks = {
    "focused": (
        Path(".omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt"),
        ["46 passed", "[100%]"],
    ),
    "full": (
        Path(".omo/ulw-loop/evidence/paper-full-pytest.txt"),
        ["661 passed", "[100%]"],
    ),
    "manual": (
        Path(".omo/ulw-loop/evidence/paper-blockers-manual-qa.txt"),
        [
            "repair_parse=pass",
            "repair_incomplete_position=pass",
            "cache_guard=pass",
            "split_report=pass",
            "malformed_persisted_rows=pass",
        ],
    ),
    "security": (
        Path(".omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt"),
        ["no violations in 4 file(s)"],
    ),
    "diff": (
        Path(".omo/ulw-loop/evidence/paper-diff-check.txt"),
        ["diff_check=pass"],
    ),
    "refs": (
        Path(".omo/ulw-loop/evidence/paper-refs-check.txt"),
        ["refs_check=pass no refs/@refs/docs/nautilus_reference changed"],
    ),
}

failed: list[str] = []
for name, (path, needles) in checks.items():
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    ok = bool(text.strip()) and all(needle in text for needle in needles)
    print(
        f"{name}: {'pass' if ok else 'fail'} "
        f"path={path} bytes={len(text.encode('utf-8'))}"
    )
    if not ok:
        failed.append(name)

if failed:
    raise SystemExit("failed: " + ", ".join(failed))

print("artifact_validation=pass")
