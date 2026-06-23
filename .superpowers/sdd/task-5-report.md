# Task 5 Report

Status: DONE

Commit: `857f0ca test: cover strategy freshness gate regressions`

Changed files:
- `tests/test_late_consensus.py`

Focused additions:
- `test_late_consensus_stale_spot_is_rejected_by_signal_gate`
- `test_late_consensus_stale_orderbook_is_rejected_by_signal_gate`

Project-wide gates skipped per assignment: affected suite, safety scan, full pytest, Docker, lint, formatters.

## Command outputs

### Pre-add RED check

Command:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate -q
```

Output:
```text
ERROR: not found: /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate
(no match in any of [<Module test_late_consensus.py>])

ERROR: not found: /home/gyue/polysignal-lab/.worktrees/strategy-freshness-gates/tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate
(no match in any of [<Module test_late_consensus.py>])
```

Exit code: 4

### GREEN check after adding tests

Command:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate -q
```

Output:
```text
..                                                                       [100%]
```

Exit code: 0

### Commit

Command:
```bash
git add tests/test_late_consensus.py && git commit --no-verify -m "test: cover strategy freshness gate regressions"
```

Output:
```text
[feat/strategy-freshness-gates 857f0ca] test: cover strategy freshness gate regressions
 1 file changed, 51 insertions(+)
```

Exit code: 0

### Behavioral RED check against temporary missing strategy policy

Temporary mutation applied only for this check: `LateConsensusStrategy.freshness_policy` returned `None`, then was restored.

Command:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate -q
```

Output:
```text
FF                                                                       [100%]
=================================== FAILURES ===================================
__________ test_late_consensus_stale_spot_is_rejected_by_signal_gate ___________

    def test_late_consensus_stale_spot_is_rejected_by_signal_gate() -> None:
        from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
        from polysignal_lab.signal_layer.gate import SignalGate
    
        strategy = LateConsensusStrategy(_config())
        snapshot = _snapshot(
            LateConsensusScenario(
                spot=SpotState(price=101.0, price_to_beat=100.0, staleness_ms=2_000)
            )
        )
        signal = strategy.evaluate(snapshot)[0]
    
        decision = SignalGate(
            SignalConfig(dedupe_enabled=False),
            PolymarketDataConfig(max_book_staleness_ms=60_000),
            BinanceDataConfig(max_price_staleness_ms=60_000),
        ).evaluate(signal, snapshot)
    
>       assert decision.accepted is False
E       AssertionError: assert True is False
E        +  where True = GateDecision(accepted=True, signal=SignalCandidate(schema_version=1, signal_id='sig_8433170402162da7ac43', created_at=...33307693', source_signal_ids=[], order_intent=None, expiry_seconds=None, pair_id=None, hedge_leg=False), rejected=None).accepted

tests/test_late_consensus.py:270: AssertionError
________ test_late_consensus_stale_orderbook_is_rejected_by_signal_gate ________

    def test_late_consensus_stale_orderbook_is_rejected_by_signal_gate() -> None:
        from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
        from polysignal_lab.signal_layer.gate import SignalGate
    
        strategy = LateConsensusStrategy(_config())
        snapshot = _snapshot(
            LateConsensusScenario(
                books=ConsensusBooks(staleness_ms=2_000),
                spot=SpotState(price=101.0, price_to_beat=100.0),
            )
        )
        signal = strategy.evaluate(snapshot)[0]
    
        decision = SignalGate(
            SignalConfig(dedupe_enabled=False),
            PolymarketDataConfig(max_book_staleness_ms=60_000),
            BinanceDataConfig(max_price_staleness_ms=60_000),
        ).evaluate(signal, snapshot)
    
>       assert decision.accepted is False
E       AssertionError: assert True is False
E        +  where True = GateDecision(accepted=True, signal=SignalCandidate(schema_version=1, signal_id='sig_375548420b3d74f92352', created_at=...229df57b', source_signal_ids=[], order_intent=None, expiry_seconds=None, pair_id=None, hedge_leg=False), rejected=None).accepted

tests/test_late_consensus.py:296: AssertionError
=========================== short test summary info ============================
FAILED tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate - AssertionError: assert True is False
 +  where True = GateDecision(accepted=True, signal=SignalCandidate(schema_version=1, signal_id='sig_8433170402162da7ac43', created_at=...33307693', source_signal_ids=[], order_intent=None, expiry_seconds=None, pair_id=None, hedge_leg=False), rejected=None).accepted
FAILED tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate - AssertionError: assert True is False
 +  where True = GateDecision(accepted=True, signal=SignalCandidate(schema_version=1, signal_id='sig_375548420b3d74f92352', created_at=...229df57b', source_signal_ids=[], order_intent=None, expiry_seconds=None, pair_id=None, hedge_leg=False), rejected=None).accepted
```

Exit code: 1

### Restored GREEN check

Command:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_late_consensus.py::test_late_consensus_stale_spot_is_rejected_by_signal_gate tests/test_late_consensus.py::test_late_consensus_stale_orderbook_is_rejected_by_signal_gate -q
```

Output:
```text
..                                                                       [100%]
```

Exit code: 0

### Commit/state verification

Command:
```bash
git log -1 --oneline && git status --short
```

Output:
```text
857f0ca test: cover strategy freshness gate regressions
?? docs/superpowers/plans/2026-06-23-strategy-freshness-gates.md
```

Exit code: 0

## Concerns

- `docs/superpowers/plans/2026-06-23-strategy-freshness-gates.md` remains untracked outside Task 5 scope.
- Commit used `--no-verify` to avoid running project-wide hooks/gates prohibited by this task.

## PTB regression test fix
- Reproduced stale malformed-input expectation failure with `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_ptb_diff.py::test_ptb_diff_rejects_malformed_or_unsupported_inputs`.
- Updated `tests/test_ptb_diff.py` to keep malformed/unsupported inputs rejecting and to document stale raw PTB data emits a candidate for central `SignalGate` freshness rejection.
- Verified with `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_ptb_diff.py` (8 passed).
