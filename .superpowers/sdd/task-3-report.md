# Task 3 Report: Scheduler Processing and Persistence Instrumentation

## Status
Complete and committed.

## Files Changed
- `src/polysignal_lab/app/scheduler_processing.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_state.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `tests/test_health_metrics.py`
- `tests/test_scheduler_paper.py`

## Red Test
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_scheduler_records_gate_rejections_and_persists_health_snapshot tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health -q
```

Output:

```text
.F                                                                       [100%]
=================================== FAILURES ===================================
____________ test_process_signal_updates_paper_and_telegram_health _____________

tmp_path = PosixPath('/tmp/pytest-of-gyue/pytest-490/test_process_signal_updates_pa0')
snapshot = MarketSnapshot(...)
settings = Settings(...)

    async def test_process_signal_updates_paper_and_telegram_health(
        tmp_path: Path, snapshot, settings
    ) -> None:
        sig = await _signal(snapshot, settings)
        scheduler = _publishing_scheduler(tmp_path, settings)

        result = await scheduler.process_signal(sig)
        components = {component.name: component for component in scheduler.health.snapshot().components}

        assert result["published"] is True
>       assert components["telegram"].status == "ok"
               ^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'telegram'

tests/test_scheduler_paper.py:88: KeyError
------------------------------ Captured log call -------------------------------
WARNING  polysignal_lab.scheduler:scheduler_processing.py:122 No order book for token btc-5m-test-UP (signal sig_e282f1c6757b4aa6dde7)
=========================== short test summary info ============================
FAILED tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health - KeyError: 'telegram'
```

## Green Test
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_scheduler_records_gate_rejections_and_persists_health_snapshot tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health -q
```

Output:

```text
..                                                                       [100%]
```

## Final Post-Commit Verification
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_scheduler_records_gate_rejections_and_persists_health_snapshot tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health -q
```

Output:

```text
..                                                                       [100%]
```

## Commit
`2305dbc5675ef747b13ebbdd1b28f0d1c4b56e8a` (`feat: record scheduler health metrics`)

Commit contents verified with:

```bash
git show --stat --oneline HEAD
```

Output:

```text
2305dbc feat: record scheduler health metrics
 src/polysignal_lab/app/scheduler_processing.py | 39 ++++++++++++++++++++++++++
 src/polysignal_lab/app/scheduler_reporting.py  |  4 +++
 src/polysignal_lab/app/scheduler_runtime.py    |  4 +++
 src/polysignal_lab/app/scheduler_state.py      |  5 ++++
 tests/test_health_metrics.py                   | 23 +++++++++++++++
 tests/test_scheduler_paper.py                  | 16 +++++++++++
 6 files changed, 91 insertions(+)
```

## Self-Review
- Snapshot builder increments build/failure metrics and records max freshness lag on successful builds.
- Signal gate accepted and rejected outcomes update `signal_gate` health metrics and status.
- Direct paper simulator processing records wallet snapshots, fills, and reject reasons.
- Resting-order fill/reject/cancel paths record paper simulator metrics and wallet snapshots for terminal rejects/cancels.
- Telegram signal, paper-result, and daily-report publish paths call `scheduler_health.note_publish_result`.
- State persistence marks JSONL/SQLite write success and SQLite write failure.
- Runtime loop and stop path persist health snapshots before sleeping/closing SQLite.
- Task 3 tests cover gate rejection snapshot persistence and process-signal Telegram/paper health counters.

## Concerns
- Targeted Task 3 tests passed; no project-wide commands, Docker, formatters, or live API calls were run per assignment constraints.
- Existing untracked `docs/superpowers/plans/2026-06-23-health-metrics-wiring.md` was present before this task and was not touched or committed.

## Fix: Storage Health Attribution

## Status
Complete; targeted checks passed before commit.

## Change
- Split `persist_state()` persistence into independent JSONL, SQLite, and state-file write sections.
- JSONL append failures now mark `jsonl_storage` down, state-file failures mark `state_storage` down, and SQLite insert failures mark `sqlite_storage` down.
- Added regression coverage proving JSONL/state-file failures do not mark `sqlite_storage` down.

## Red Test
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_persist_state_marks_jsonl_failure_without_sqlite_down tests/test_health_metrics.py::test_persist_state_marks_state_failure_without_sqlite_down -q
```

Output:

```text
FAILED tests/test_health_metrics.py::test_persist_state_marks_jsonl_failure_without_sqlite_down - KeyError: 'jsonl_storage'
FAILED tests/test_health_metrics.py::test_persist_state_marks_state_failure_without_sqlite_down - KeyError: 'state_storage'
```

## Green Test
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_scheduler_records_gate_rejections_and_persists_health_snapshot tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health tests/test_health_metrics.py::test_persist_state_marks_jsonl_failure_without_sqlite_down tests/test_health_metrics.py::test_persist_state_marks_state_failure_without_sqlite_down tests/test_health_metrics.py::test_refresh_markets_marks_jsonl_failure_without_sqlite_down -q
```

Output:

```text
.....                                                                    [100%]
```

## Concerns
- No project-wide build/test/lint, formatter, Docker, or live services were run per assignment constraints.
