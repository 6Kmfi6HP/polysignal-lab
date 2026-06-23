# Todo 7 CLOB Midpoint Repair Gate Review

recommendation: REJECT

AdversarialVerify verdict: needs-human-review
confidence: high

## originalIntent

Todo 7 is to align public market-data contracts with official public APIs: Gamma active event pagination/filtering, Polymarket public CLOB book/midpoint/spread parsing, Polymarket public market WebSocket book/price/best-bid-ask/last-trade/lifecycle handling, and Binance public bookTicker spot updates. It must add official-payload fixtures and must not send auth headers or add trading endpoints.

## desiredOutcome

The user should be able to check off Todo 7 only when current source, fixtures, tests, and evidence prove public official payload shapes are parsed, malformed public events are ignored safely, authenticated/trading surfaces are absent, scoped Python quality is acceptable, and required review artifacts are present and supported.

## userOutcomeReview

The CLOB midpoint repair itself is confirmed from current disk state. `get_mid` parses `mid_price` before the backward-compatible `mid` and `midpoint` fallback keys, the fixture contains only `{"mid_price": "0.475"}`, and the focused CLOB test asserts that exact official fixture shape before parsing. The requested tests, auth guard, py_compile, prompt-injection probe, and LOC/quality scans passed.

Final gate approval is still blocked by missing Todo 7 review artifact coverage required by the gate process. No Todo 7-specific standalone code-review report, manual QA matrix, or notepad path was found under `.omo/evidence/`, and the prior gate report already recorded that artifact gap.

## blockers

1. Missing Todo 7 standalone code-review report with explicit `programming` and `remove-ai-slops` overfit/slop coverage. Evidence: `.omo/evidence/todo-7-gate-review.md:33` records the absence, and a current `.omo/evidence` file listing shows no `todo-7` or `task-7` code-review artifact.

2. Missing Todo 7 manual QA matrix and notepad path as separate artifacts. Evidence: `.omo/evidence/todo-7-gate-review.md:33`, `.omo/evidence/todo-7-gate-review.md:81`, `.omo/evidence/todo-7-gate-review.md:82`, and `.omo/evidence/todo-7-gate-review.md:83`.

## codeRepairEvidence

- `src/polysignal_lab/data/polymarket_clob_rest.py:25` through `src/polysignal_lab/data/polymarket_clob_rest.py:27`: `get_mid` reads `/midpoint` and returns `safe_float(payload.get("mid_price") or payload.get("mid") or payload.get("midpoint"))`.
- `tests/fixtures/public_market_payloads.json:147` through `tests/fixtures/public_market_payloads.json:149`: `clob_midpoint` is exactly `{"mid_price": "0.475"}`.
- `tests/test_market_data.py:114` through `tests/test_market_data.py:139`: focused CLOB REST test asserts the official midpoint fixture shape and validates parsed `mid == 0.475`, spread, book, token_id params, and no auth headers.
- Official Polymarket docs checked during this review: `https://docs.polymarket.com/api-reference/data/get-midpoint-price` shows the 200 response field as `mid_price` and describes it as a required string.

## checkedArtifactPaths

- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `tests/fixtures/public_market_payloads.json`
- `tests/test_market_data.py`
- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/data/binance_spot_ws.py`
- `tests/test_websocket_contracts.py`
- `.omo/evidence/task-7-complete-prd-old-remove-demo.txt`
- `.omo/evidence/todo-7-gate-review.md`
- `docs/EXTERNAL_API_RESEARCH.md`
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/start-work/ledger.jsonl`
- `git status --short`

## reproCommands

- `.venv/bin/python -m pytest tests/test_market_data.py tests/test_websocket_contracts.py -q` -> PASS, 9 tests.
- `.venv/bin/python -m pytest tests/test_market_data.py::test_clob_rest_public_book_mid_and_spread_parsing_handles_official_shapes -q` -> PASS, 1 test.
- `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_polymarket_price_changes_event_updates_registry tests/test_websocket_contracts.py::test_polymarket_book_best_bid_ask_last_trade_and_lifecycle_events_are_public_contract_safe tests/test_websocket_contracts.py::test_binance_bookticker_updates_spot_registry tests/test_websocket_contracts.py::test_malformed_public_market_events_are_ignored_without_crash -q` -> PASS, 4 tests.
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|submit_order|order submit" src/polysignal_lab/data src/polysignal_lab/app'` -> PASS, no matches.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile src/polysignal_lab/data/polymarket_clob_rest.py src/polysignal_lab/data/polymarket_market_discovery.py src/polysignal_lab/data/polymarket_clob_ws.py src/polysignal_lab/data/binance_spot_ws.py tests/test_market_data.py tests/test_websocket_contracts.py` -> PASS.
- `for f in ...; awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#)/' "$f" | wc -l; done` -> `31`, `115`, `128`, `78`, `108`, `80`; all <= 250 pure LOC.
- Quality grep for `Any`, `cast(`, `type: ignore`, `import asyncio`, `import pandas`, broad exceptions, raw `dict[str, Any]`/`dict[str, object]`, `print`, `TODO`, `eval`, and `exec` over scoped Todo 7 Python files -> PASS, no matches.
- `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_polymarket_public_payload_text_is_not_executed -q && test ! -e /tmp/polysignal_prompt_injection` -> PASS.

## adversarialProbeResults

- stale_state: PASS for code repair. Current disk state has `mid_price` in parser, fixture, and CLOB test. Prior rejected evidence is superseded for the midpoint bug by current source and final task evidence lines `.omo/evidence/task-7-complete-prd-old-remove-demo.txt:579` through `.omo/evidence/task-7-complete-prd-old-remove-demo.txt:584`.
- misleading_success_output: PASS for code repair. The CLOB test no longer uses implementation-only `mid`; it asserts `{"mid_price": "0.475"}` before parsing.
- malformed_input: PASS. The focused malformed WebSocket test passed.
- prompt_injection: PASS. Public payload text is inert and `/tmp/polysignal_prompt_injection` is absent after the focused test.
- authenticated_client_guard: PASS. The requested forbidden auth/trading grep over `src/polysignal_lab/data` and `src/polysignal_lab/app` produced no matches.
- programming_quality: PASS on scoped Todo 7 Python files. All files are below the 250 pure-LOC ceiling and the quality grep is clean.
- remove_ai_slops_overfit: PASS on direct code/test pass for the midpoint repair. No deletion-only, tautological, or implementation-mirroring CLOB midpoint test remains after aligning the fixture with official docs; no unnecessary production extraction was added by the repair.
- dirty_worktree: REVIEWED. The worktree remains broadly dirty and untracked; this review inspected only and did not revert unrelated changes.
- env_secrecy: PASS. `.env` was not read.

## exactEvidenceGaps

- No Todo 7 standalone code-review artifact with explicit skill-perspective and overfit/slop criterion coverage was found.
- No Todo 7 manual QA matrix artifact separate from executor command transcript was found.
- No notepad path was provided or found for Todo 7.

## conclusion

The CLOB midpoint repair is technically confirmed, but Todo 7 cannot receive final gate approval under the provided final-review criteria until the missing review/manual-QA/notepad artifacts are supplied or the gate owner explicitly waives those artifact requirements.
