# Todo 10 Manual QA Notepad

Manual QA scope:
- Verify Late Consensus PRD acceptance and failure selectors.
- Verify forbidden asset names remain absent.
- Verify touched Python files compile and stay within LOC guardrails.

Executed scenarios:

1. Happy QA
   - Invocation: `.venv/bin/python -m pytest tests/test_late_consensus.py::test_late_consensus_emits_multi_asset_signal_with_metrics -q`
   - Result: exit code 0, output `. [100%]`
   - Observable: BTC/ETH/SOL/XRP all emit `late_consensus` BUY_UP candidates with `LATE_CONSENSUS_*` reason codes and metrics for ask_sum, confidence_abs, max_spread, orderbook freshness, spot freshness, and spot movement.

2. Failure QA
   - Invocation: `.venv/bin/python -m pytest tests/test_late_consensus.py::test_late_consensus_rejects_wide_spread tests/test_late_consensus.py::test_late_consensus_rejects_stale_spot_or_flip_guard -q`
   - Result: exit code 0, output `.. [100%]`
   - Observable: wide spread rejects; stale Binance spot rejects; rapid favorite-side flip rejects.

3. Repeated flip guard QA
   - Red invocation: `.venv/bin/python -m pytest tests/test_late_consensus.py::test_late_consensus_rejects_repeated_flip_inside_guard -q`
   - Red result: exit code 1, output showed `second_down_signals` contained one `SignalCandidate` instead of `[]`.
   - Green invocation: `.venv/bin/python -m pytest tests/test_late_consensus.py::test_late_consensus_rejects_repeated_flip_inside_guard -q`
   - Green result: exit code 0, output `. [100%]`
   - Observable: first UP emits, first immediate DOWN is blocked, and second immediate DOWN remains blocked after the first blocked flip.

4. Full Todo 10 suite
   - Invocation: `.venv/bin/python -m pytest tests/test_late_consensus.py tests/test_strategies.py -q`
   - Result: exit code 0, output `........... [100%]`
   - Observable: new dedicated tests and existing strategy tests pass together.

5. Downstream smoke
   - Invocation: `.venv/bin/python -m pytest tests/test_signal_layer.py::test_consensus_engine_merges_two_strategies -q`
   - Result: exit code 0, output `. [100%]`
   - Observable: Late Consensus still participates in consensus signal generation.

6. Compile and quality
   - Invocation: `.venv/bin/python -m py_compile src/polysignal_lab/strategies/late_consensus.py tests/test_late_consensus.py`
   - Result: exit code 0, empty output.
   - Invocation: `if rg -n 'Any|cast\(|type: ignore|import asyncio|import pandas|except Exception|except BaseException|dict\[str, Any\]|dict\[str, object\]' src/polysignal_lab/strategies/late_consensus.py tests/test_late_consensus.py; then exit 1; else exit 0; fi`
   - Result: exit code 0, empty output.
   - Invocation: `for f in src/polysignal_lab/strategies/late_consensus.py tests/test_late_consensus.py; do printf '%s ' "$f"; awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|--)/' "$f" | wc -l; done`
   - Result: exit code 0, output `src/polysignal_lab/strategies/late_consensus.py 199`, `tests/test_late_consensus.py 177`.

7. Forbidden asset surface
   - Invocation: `paths=(config src tests docs README.md); if [ -e compliance ]; then paths+=(compliance); fi; if rg -n 'DOGE|BNB|HYPE' "$paths[@]" -g '!*.env'; then exit 1; else exit 0; fi`
   - Result: exit code 0, empty output.
   - Observable: `compliance` is absent in this checkout; existing required surfaces are clean.

Notes:
- `.env` was not read.
- No long-lived processes were started.
- Spot movement is validated as signed Binance spot price versus PTB because that is the current strategy snapshot input surface.
