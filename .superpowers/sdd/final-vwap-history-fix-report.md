

## VWAP trade-history gate rejection fix

- Added failing regression coverage showing a stale VWAP candidate rejected by the signal gate must roll back the candidate snapshot's pending trade-history samples, otherwise the next fresh calculation is polluted.
- Added scheduler coverage showing rejected gate decisions notify the originating strategy before rejection persistence.
- Implemented `BaseStrategy.notify_signal_rejected(...)` as a default no-op, scheduler rejection notification, and VWAP pending-sample rollback while preserving `notify_signal_accepted(...)` one-shot guard behavior and accepted samples.
- RED: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_vwap_momentum.py -q` failed with missing `notify_signal_rejected` and stale latest price `0.6 != 0.52`.
- GREEN: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_vwap_momentum.py -q` passed: `12 passed`.
- Covering regression: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_vwap_momentum.py tests/test_late_consensus.py tests/test_signal_gate.py -q` passed: `35 passed`.

- Code review: `ReviewVWAPHistory` reported no Critical, Important, or Minor findings.
- Final post-amend covering run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_vwap_momentum.py tests/test_late_consensus.py tests/test_signal_gate.py -q` passed: `35 passed`.
