# Todo 11 Manual QA Notepad

Manual QA scenarios executed:

1. BUY_UP and BUY_DOWN acceptance
- Invocation: `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_emits_buy_up_and_down_from_trigger_rows -q`
- Result: pass.
- Observable: emitted UP and DOWN candidates include `PTB_SPOT_ABOVE_PTB`/`PTB_SPOT_BELOW_PTB`, `PTB_PROBABILITY_EDGE_OK`, trigger names, token ask, directional probability, probability edge, and max entry price metrics.

2. Token-price rejection
- Invocation: `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_rejects_above_max_token_price -q`
- Result: pass.
- Observable: no signal when side ask is `0.79` against `max_token_price=0.78`.

3. Probability-edge rejection
- Invocation: `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_rejects_below_probability_edge -q`
- Result: pass.
- Observable: no signal when token ask `0.93` leaves only `0.07` edge against `min_probability_edge=0.08`.

4. Diff and direction rejection
- Invocation: covered by `.venv/bin/python -m pytest tests/test_ptb_diff.py tests/test_strategies.py -q`
- Result: pass.
- Observable: no signal below `min_diff_usd=80`, and no UP signal when spot is below PTB.

5. Time-window rejection
- Invocation: covered by `.venv/bin/python -m pytest tests/test_ptb_diff.py tests/test_strategies.py -q`
- Result: pass.
- Observable: no signal at 29 seconds or 181 seconds for a 30-180 second trigger window.

6. Malformed input rejection
- Invocation: covered by `.venv/bin/python -m pytest tests/test_ptb_diff.py tests/test_strategies.py -q`
- Result: pass.
- Observable: missing PTB, missing spot, missing side book, unverified PTB, wrong asset, unsupported timeframe, missing seconds, stale data, and wide spread all reject safely.

7. Runtime YAML parse
- Invocation: `.venv/bin/python - <<'PY' ... Settings.from_yaml('config/signal_bot.yaml') ... PY`
- Result: pass.
- Observable: first trigger is `strong_up_late`, max token price is `0.78`, second trigger side is `DOWN`.

Notes:
- No dev server or long-lived process was started.
- No `.env` contents were read.
- No real trading behavior was invoked or added.
