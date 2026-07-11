from pathlib import Path


def _script() -> str:
    return Path("docker-entrypoint.sh").read_text(encoding="utf-8")


def test_entrypoint_defaults_to_nautilus() -> None:
    source = _script()
    assert 'case "${1:-nautilus}" in' in source
    assert "--mode nautilus" in source


def test_entrypoint_retires_scheduler_execution_mode() -> None:
    source = _script()
    scheduler = source.split("scheduler)", 1)[1].split(";;", 1)[0]
    assert "retired" in scheduler.lower()
    assert "python -m polysignal_lab.app.main" not in scheduler
    assert "exit 2" in scheduler
    assert 'Usage: $0 {nautilus|dashboard|test|shell|smoke}' in source
