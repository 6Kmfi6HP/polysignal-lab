from pathlib import Path

checks = [
    (
        "full pytest artifact validity",
        Path(".omo/ulw-loop/evidence/paper-full-pytest.txt"),
        "661 passed",
    ),
    (
        "security scope",
        Path(".omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt"),
        "no violations in 4 file(s)",
    ),
    (
        "diff check",
        Path(".omo/ulw-loop/evidence/paper-diff-check.txt"),
        "diff_check=pass",
    ),
    (
        "refs clean",
        Path(".omo/ulw-loop/evidence/paper-refs-check.txt"),
        "refs_check=pass no refs/@refs/docs/nautilus_reference changed",
    ),
]

for label, path, marker in checks:
    text = path.read_text(encoding="utf-8")
    bad = any(token in text.lower() for token in ("failed", "error", "traceback"))
    ok = bool(text.strip()) and marker in text and not (bad and marker not in text)
    print(
        f"{label}: {'pass' if ok else 'fail'} marker={marker!r} "
        f"path={path} bytes={len(text.encode('utf-8'))}"
    )
    if not ok:
        raise SystemExit(f"{label} invalid")

print("regression_artifact_validation=pass")
