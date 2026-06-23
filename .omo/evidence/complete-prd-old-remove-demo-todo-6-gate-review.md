recommendation: REJECT

originalIntent:
- Complete Todo 6 from `.omo/plans/complete-prd-old-remove-demo.md`: repair scheduler startup order and subscription lifecycle.
- Required behavior: load config, validate live Telegram settings, load enabled assets/strategies, initialize paper wallet, discover current Polymarket crypto Up/Down markets, then start Polymarket market WebSocket and Binance spot stream.
- Required subscription behavior: subscribe only after token discovery, prevent empty Polymarket subscriptions, stop stale market subscriptions, and resubscribe when token sets change.
- Required safety boundary: do not add authenticated Polymarket market/order clients.

desiredOutcome:
- User-visible scheduler startup should validate live Telegram publishing credentials before market discovery, discover markets before starting stream subscriptions, and only subscribe Polymarket market WS with non-empty discovered token ids.
- Empty discovery should not send an empty subscription and should stop a stale subscription.
- Changed token sets should stop the old market WS subscription and start a new non-empty subscription.
- Evidence should include passing focused pytest runs, safety grep, programming-quality scan, manual QA proof, and a code-review report that explicitly covers programming and remove-ai-slops/overfit criteria.

userOutcomeReview:
- Functional happy-path and focused subscription tests pass: `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_market_data.py -q` produced `7 passed`; the named startup/subscription, empty-refresh, and token-set-change tests also passed.
- The tests prove the normal-path order and token behavior, but they do not prove failure-path startup correctness. A direct adversarial probe showed that if initial discovery raises, `run()` logs the error and still calls `start_websockets`.
- That behavior conflicts with the intended startup sequence because successful initial discovery is no longer a gate before stream startup. It is caused by a newly added broad `except Exception` in the Todo 6 diff.
- The Todo 6 code-review report artifact with explicit programming/remove-ai-slops overfit coverage is absent, so the report-coverage requirement is unmet.

blockers:
- `src/polysignal_lab/app/scheduler.py:675-679` newly adds `except Exception as exc` around the initial `refresh_markets_once()` / `_fetch_resolved_markets()` startup block, logs, and continues to `start_websockets()` at line 682. This is a new broad-exception escape hatch under the programming/remove-ai-slops criteria and creates false confidence for startup-order completion.
- Adversarial probe result: a temporary scheduler with `refresh_markets_once()` raising `RuntimeError("discovery failed")` produced `['discover', 'streams_started']`, proving websocket startup still occurs after failed initial discovery.
- No standalone Todo 6 code-review report was found under `.omo/evidence/`; only Todo 3/4 review artifacts exist. Developer gate criteria require explicit code-review report coverage for programming and remove-ai-slops/overfit/slop criteria.
- `src/polysignal_lab/app/scheduler.py` remains oversized: direct pure-LOC scan reports 653 non-blank/non-comment lines. The size is inherited, but Todo 6 added more lifecycle state and helpers to that oversized module. This is a risk; the hard blocker is the new broad exception plus missing review artifact.

checkedArtifactPaths:
- `.omo/plans/complete-prd-old-remove-demo.md`
- `docs/PRD-old.md`
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/data/binance_spot_ws.py`
- `tests/test_scheduler.py`
- `tests/test_market_data.py`
- `.omo/evidence/task-6-complete-prd-old-remove-demo.txt`
- `.omo/start-work/ledger.jsonl`
- `.omo/evidence/`
- `git status --short`

commandsInspected:
- `nl -ba docs/PRD-old.md | sed -n '150,172p'` confirmed PRD startup lines 158-164.
- `nl -ba .omo/plans/complete-prd-old-remove-demo.md | sed -n '145,153p'` confirmed Todo 6 requirements and acceptance criteria.
- `mcp__codegraph.codegraph_node` inspected current `scheduler.py`, `polymarket_clob_ws.py`, `binance_spot_ws.py`, `tests/test_scheduler.py`, and `tests/test_market_data.py`.
- `git diff -U3 -- src/polysignal_lab/app/scheduler.py` showed the new Telegram validation, token tracking, websocket lifecycle changes, and new broad startup catch.
- `git status --short` showed a broadly dirty worktree with the claimed scheduler change and untracked `.omo/`, `docs/`, and `tests/` artifacts.

reproCommands:
- `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_market_data.py -q` -> `7 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_refresh_markets_before_starting_streams tests/test_scheduler.py::test_market_ws_subscribes_after_token_discovery -q` -> `2 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_empty_market_refresh_does_not_subscribe_market_ws -q` -> `1 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_market_ws_resubscribes_when_token_set_changes -q` -> `1 passed`
- `if rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|order submit|submit_order" src/polysignal_lab/app src/polysignal_lab/data; then exit 1; else exit 0; fi` -> exit 0, no matches
- `.venv/bin/python -m py_compile src/polysignal_lab/app/scheduler.py tests/test_scheduler.py tests/test_market_data.py` -> exit 0
- `.venv/bin/python -m ruff check src/polysignal_lab/app/scheduler.py tests/test_scheduler.py tests/test_market_data.py` -> exit 1, `No module named ruff`
- `rg -n "\bAny\b|cast\(|type:\s*ignore|import asyncio|import pandas|except Exception|except BaseException|->\s*dict\b|:\s*dict\b" src/polysignal_lab/app/scheduler.py tests/test_scheduler.py tests/test_market_data.py` -> showed inherited `import asyncio`, many inherited broad catches/raw dicts, and the new broad catch at `scheduler.py:678`
- `git diff -U0 -- src/polysignal_lab/app/scheduler.py | rg -n "^\+.*(Any\b|cast\(|type:\s*ignore|import asyncio|import pandas|except Exception|except BaseException|->\s*dict\b|:\s*dict\b)|^@@"` -> showed only one newly added forbidden quality pattern: `+        except Exception as exc`
- `for f in src/polysignal_lab/app/scheduler.py tests/test_scheduler.py tests/test_market_data.py; do awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' "$f" | wc -l; done` -> scheduler 653, scheduler tests 147, market-data tests 29
- Adversarial Python probe in `/tmp` with `refresh_markets_once()` raising -> printed `initial refresh_markets_once failed: discovery failed` and `['discover', 'streams_started']`

removeAiSlopsAndProgrammingReview:
- Loaded and applied `/home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/remove-ai-slops/SKILL.md`.
- Loaded and applied `/home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/SKILL.md` and `references/python/README.md`.
- Direct slop pass found the focused tests are mostly behavior-oriented and not deletion-only or tautological for the requested subscription behavior.
- Direct slop/programming pass found unresolved production slop: the new broad `except Exception` hides startup discovery failure and allows stream startup after failed discovery.
- Direct programming pass found the module-size risk remains above the 250 pure-LOC threshold; this was inherited but worsened by Todo 6 additions.

exactEvidenceGaps:
- Missing standalone Todo 6 code-review report with explicit `programming` and `remove-ai-slops` overfit/slop criterion coverage.
- No passing lint evidence because ruff is unavailable in `.venv`.
- No test covers initial discovery failure as a startup gate; current implementation demonstrably starts streams after failed initial discovery.

confidence: high
