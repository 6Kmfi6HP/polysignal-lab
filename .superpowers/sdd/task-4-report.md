# Task 4 Report: PTB Diff Gate Cutover and Rejected Details Persistence

Status: DONE

Commit: b4959bd refactor: route ptb freshness through signal gate

## Changes

- Added PTB stale spot cutover regression test proving PTBDiffStrategy still emits a candidate and SignalGate rejects it with structured STALE_SPOT_PRICE freshness details.
- Removed PTBDiffStrategy's duplicate raw orderbook/spot freshness `continue` drops while preserving freshness diagnostics in candidate metrics, including `max_lag_ms`.
- Added dashboard regression coverage proving persisted rejected signal `reason_code` and structured `details` are returned by `/api/rejected-signals`.

## RED

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate -q
```

Output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____________ test_ptb_diff_stale_spot_candidate_is_rejected_by_gate ____________

snapshot = MarketSnapshot(schema_version=1, snapshot_id='snap_164fe26cf966bcfd', created_at=datetime.datetime(2026, 6, 23, 14, 23..., up_ask=0.82, down_ask=0.18, max_spread=0.03, ask_sum=1.0, ask_skew=0.6399999999999999, favorite_side=<Side.UP: 'UP'>)
settings = Settings(app=AppConfig(name='PolySignal Lab', environment='production', mode='signal_plus_paper', timezone='Asia/Bangk..._entry_price=0.85, max_spread=0.05, base_confidence=0.55, max_confidence=0.9, min_confidence=0.4, max_skew_ratio=0.5)))

    async def test_ptb_diff_stale_spot_candidate_is_rejected_by_gate(snapshot, settings) -> None:
        stale_snapshot = snapshot.model_copy(
            update={
                "spot": snapshot.spot.model_copy(
                    update={"received_at": snapshot.created_at - timedelta(seconds=3)}
                ),
                "freshness": snapshot.freshness.model_copy(update={"spot_ms": 3_000, "max_ms": 3_000}),
            }
        )
        strategy = PTBDiffStrategy(settings.strategies.ptb_diff)
        signals = strategy.evaluate(stale_snapshot)

>       assert signals
E       assert []

tests/test_signal_gate.py:297: AssertionError
=========================== short test summary info ============================
FAILED tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate - assert []
```

## GREEN focused PTB test

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate -q
```

Output:

```text
.                                                                        [100%]
```

## Task 4 focused tests

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q
```

Output:

```text
..                                                                       [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## Storage/dashboard regression tests

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_dashboard.py -q
```

Output:

```text
.............                                                            [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## Commit

Command:

```bash
git add src/polysignal_lab/strategies/ptb_diff.py tests/test_signal_gate.py tests/test_dashboard.py && git commit -m "refactor: route ptb freshness through signal gate"
```

Output:

```text
Staged whitespace check..................................................Passed
Python syntax compile....................................................Passed
PolySignal safety scan...................................................Passed
Commit message policy....................................................Passed
[feat/strategy-freshness-gates b4959bd] refactor: route ptb freshness through signal gate
 3 files changed, 47 insertions(+), 6 deletions(-)
```

## Commit verification

Command:

```bash
git show --stat --oneline --no-renames --format=medium b4959bd -- src/polysignal_lab/strategies/ptb_diff.py tests/test_signal_gate.py tests/test_dashboard.py
```

Output:

```text
commit b4959bd
Author: gyue <gyue@example.com>
Date:   Tue Jun 23 21:24:23 2026 +0700

    refactor: route ptb freshness through signal gate

 src/polysignal_lab/strategies/ptb_diff.py |  6 +-----
 tests/test_dashboard.py                   | 19 ++++++++++++++++++-
 tests/test_signal_gate.py                 | 28 ++++++++++++++++++++++++++++
 3 files changed, 47 insertions(+), 6 deletions(-)
```

## Concerns

- Focused and regression tests emit the existing StarletteDeprecationWarning from FastAPI TestClient/httpx; tests pass.
- Project-wide gates were intentionally skipped per assignment.

## Review fix: PTB stale-orderbook reason code

Status: DONE

### RED

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason -q
```

Output:

```text
F                                                                        [100%]
FAILED tests/test_signal_gate.py::test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason - AssertionError: assert 'PTB_ORDERBOOK_FRESH' not in [...]
```

### GREEN focused PTB review test

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason -q
```

Output:

```text
.                                                                        [100%]
```

### Task 4 focused dashboard/gate tests

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q
```

Output:

```text
...                                                                      [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

### Storage/dashboard regression tests

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_dashboard.py -q
```

Output:

```text
.............                                                            [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

### Commit

Command:

```bash
git commit -m "fix: correct ptb stale orderbook reason code"
```

Output:

```text
Staged whitespace check..................................................Passed
Python syntax compile....................................................Passed
PolySignal safety scan...................................................Passed
Commit message policy....................................................Passed
[feat/strategy-freshness-gates 66cd72f] fix: correct ptb stale orderbook reason code
 2 files changed, 37 insertions(+), 1 deletion(-)
```

### Final verification

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q
```

Output:

```text
...                                                                      [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

Command:

```bash
git show -s --format='%h %s' HEAD
```

Output:

```text
66cd72f fix: correct ptb stale orderbook reason code
```

## Review fix: remove PTB_ORDERBOOK_FRESH from all PTB candidates

Status: DONE

### RED

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason -q
```

Output:

```text
F                                                                        [100%]
FAILED tests/test_signal_gate.py::test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason - AssertionError: assert 'PTB_ORDERBOOK_FRESH' not in ['PTB_SPOT_ABOVE_PTB', 'PTB_DIFF_THRESHOLD_OK', 'PTB_TOKEN_PRICE_OK', 'PTB_PROB_RANGE_OK', 'PTB_TIME_WINDOW_OK', 'PTB_ORDERBOOK_FRESH', ...]
```

### GREEN focused reason-code test

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason -q
```

Output:

```text
.                                                                        [100%]
```

### Covering tests

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_gate.py::test_ptb_diff_fresh_orderbook_candidate_has_metrics_not_fresh_reason tests/test_signal_gate.py::test_ptb_diff_stale_orderbook_candidate_has_no_fresh_reason tests/test_signal_gate.py::test_ptb_diff_stale_spot_candidate_is_rejected_by_gate tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q
```

Output:

```text
....                                                                     [100%]
=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

### Source check

Command:

```text
search PTB_ORDERBOOK_FRESH in src and tests
```

Output:

```text
PTB_ORDERBOOK_FRESH remains only in negative test assertions under tests/test_signal_gate.py.
```
