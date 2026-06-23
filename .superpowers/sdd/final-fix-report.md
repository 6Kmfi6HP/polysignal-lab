# Final Fix Report: Late Consensus Gate-Acceptance State

Status: DONE

Commit: fix: defer late consensus state until gate accept

## Changes

- Added `BaseStrategy.notify_signal_accepted(signal)` and call it only after `SignalGate` accepts a candidate in scheduler processing.
- Moved LateConsensusStrategy entry-frequency and flip-guard state mutation from candidate generation to accepted-signal notification.
- Added regression coverage proving stale gate-rejected late-consensus candidates do not consume entry-frequency or flip-guard state, while a fresh gate-accepted candidate still throttles immediate repeats.

## RED

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_gate_rejection_does_not_consume_entry_state -q
```

Observed failure:

```text
FAILED tests/test_late_consensus.py::test_late_consensus_gate_rejection_does_not_consume_entry_state - assert 0 == 1
```

## GREEN focused test

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_gate_rejection_does_not_consume_entry_state -q
```

Output:

```text
.                                                                        [100%]
```

## Focused regression tests

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py tests/test_strategies.py::test_late_consensus_generates_favorite_side tests/test_strategies.py::test_late_consensus_flip_guard_blocks_recent_flip tests/test_signal_layer.py::test_consensus_engine_merges_two_strategies -q
```

Output:

```text
..............                                                           [100%]
```

## Notes

- Used the preferred scheduler hook pattern because `evaluate_once()` still has the originating strategy in scope at the exact gate-accepted decision point.
- Project-wide gates, lint, formatters, Docker, and broad safety scans were intentionally skipped per assignment.
