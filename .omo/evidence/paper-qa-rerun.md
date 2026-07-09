# Paper QA Rerun

Verdict: PASS

Scope: `/home/debian/polysignal-lab`

Notes:
- Product code was not modified by this QA run.
- The required source evidence file `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt` contains pytest output only, not the original command. I reran the focused paper blocker suite with the repo's `uv run pytest` pattern and then a broader adjacent suite covering 45 tests.
- The required manual source evidence file `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt` contains pass output only, not driver source. I reran an equivalent inline Python driver with real imports and assertions.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | focused paper blocker tests | CLI pytest | `uv run pytest -p no:cacheprovider --no-header tests/test_repair_settlement_results.py tests/test_scheduler_cancelled_markets.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_reporting.py tests/test_storage_reporting_publish.py tests/test_storage_restore.py tests/test_strategy_stats.py` | PASS: `40 passed, 2 warnings`, exit 0 | A1 |
| S2 | focused paper blocker tests, broadened adjacency | CLI pytest | `uv run pytest -p no:cacheprovider --no-header tests/test_repair_settlement_results.py tests/test_scheduler_cancelled_markets.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_reporting.py tests/test_storage_reporting_publish.py tests/test_storage_restore.py tests/test_strategy_stats.py tests/test_publish_service.py` | PASS: `45 passed, 2 warnings`, exit 0 | A2 |
| S3 | repair result row parser path, incomplete cache guard, SPLIT daily report behavior, malformed persisted paper rows | CLI Python driver | `PYTHONPATH=tests uv run python - <<'PY' ... PY` | PASS: printed `repair_parse=pass`, `cache_guard=pass`, `split_report=pass`, `malformed_persisted_rows=pass`; exit 0 | A3 |
| S4 | cleanup/process check | CLI process/tmux audit | `tmux ls; pgrep -af "ulw-qa\|python.*paper-qa-rerun\|uvicorn.*polysignal\|vite.*polysignal\|pytest.*paper" \| rg -v "pgrep\|rg\|cleanup-process-check"` | PASS: no tmux server and no QA-spawned process rows | A4 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV1 | repair result row parser path | Repair script returns a trade-result row that must satisfy the typed paper result parser | `_settle_for_repair(...)` returns a parseable row with a generated `paper_trade_id`, original `signal_id`, and terminal `WIN` result | PASS | A3 |
| ADV2 | incomplete cache guard | Scheduler has `nautilus_cache=object()` and a shadow wallet with non-default equity/open positions | Reporting ignores incomplete cache and returns `(1000.0, 1000.0, 0)` instead of falling back to shadow wallet values | PASS | A3 |
| ADV3 | SPLIT daily report behavior | Daily report receives a `SPLIT` result with positive PnL | SPLIT counts as one closed position, not win/loss/void, and preserves PnL | PASS | A3 |
| ADV4 | malformed persisted paper rows | API insert and already-persisted SQLite row are missing required paper result fields | API insert raises `InvalidPaperTradeResultRow`; restore/query filters the malformed persisted row to `[]` | PASS | A3 |
| ADV5 | wrong interpreter guard | Plain `pytest` outside the repo environment cannot import `nautilus_trader` | QA does not count this as product failure; faithful repo invocation uses `uv run pytest` and passes | PASS | A1, A2 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | CLI transcript | Focused paper blocker pytest rerun: 40 tests passed with the repo `uv run` invocation | `.omo/evidence/paper-qa-rerun/focused-pytest.txt` |
| A2 | CLI transcript | Broader focused paper blocker pytest rerun including publish adjacency: 45 tests passed | `.omo/evidence/paper-qa-rerun/focused-pytest-broad.txt` |
| A3 | CLI transcript | Inline Python manual driver covering repair parser, incomplete cache guard, SPLIT report behavior, and malformed persisted rows | `.omo/evidence/paper-qa-rerun/manual-driver.txt` |
| A4 | CLI transcript | Final narrow cleanup receipt proving no QA-spawned tmux/server/browser/process rows remain | `.omo/evidence/paper-qa-rerun/cleanup-process-check-final.txt` |
| A5 | CLI transcript | Wider cleanup/process audit showing pre-existing unrelated Chrome DevTools MCP/Claude processes and no QA-spawned runtime | `.omo/evidence/paper-qa-rerun/cleanup-process-check.txt` |

