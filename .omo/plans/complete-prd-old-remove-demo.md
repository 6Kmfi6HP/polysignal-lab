# complete-prd-old-remove-demo - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** A PRD-old-complete PolySignal Lab: no demo runtime, no non-PRD default strategies, live read-only market ingestion, the three required strategies, Telegram channel publishing, paper simulation, settlement, reports, SQLite, dashboard, and current docs.

**Why this approach:** The riskiest parts are product scope cleanup and real integrations, so the work starts by replacing demo dependencies and locking safety boundaries, then fixes market data, strategy semantics, paper lifecycle, and real-surface QA in dependency order.

**What it will NOT do:** It will not add real trading, wallet/private-key handling, authenticated Polymarket order clients, redeem/transfer behavior, CEX orders, or a demo command.

**Effort:** XL
**Risk:** High - external data contracts, scheduler timing, artifact deletion, real Telegram delivery, and broad PRD final-scope acceptance all interact.
**Decisions to sanity-check:** Generated history is deleted, `.env` is preserved untouched, real Telegram send is mandatory, and PRD-old final scope includes section 26 dashboard/SQLite/consensus/daily reporting/leaderboard.

Your next move: approve execution, or run a high-accuracy Momus review of this plan first. Full execution detail follows below.

---

> TL;DR (machine): XL/high-risk full PRD-old completion plan with demo removal, generated-history deletion, real Telegram QA, market-data repairs, strategy alignment, paper lifecycle, dashboard/storage/docs, and subagent review gates.

## Scope
### Must have
- Source of truth is `docs/PRD-old.md`, including first-version, second-version, and success-metric scope.
- Product runtime has exactly the PRD strategy family: VWAP Momentum, Late Consensus, PTB Diff.
- Default runtime assets follow PRD-old: VWAP/PTB BTC, Late Consensus BTC/ETH/SOL/XRP.
- Product runtime discovers current Polymarket crypto Up/Down markets, subscribes to public CLOB market data after token discovery, reads Binance spot streams, and builds fresh normalized snapshots.
- Every accepted signal can be formatted, deduped, sent to Telegram, written to audit logs/storage, paper-filled, exited/settled, reported, and shown through a read-only dashboard.
- Real Telegram channel send is mandatory final acceptance when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` are supplied externally. Evidence must redact secrets and channel identifiers.
- Generated historical artifacts are deleted during execution: `logs/`, `state/`, `data/paper_trades.sqlite`, `data/polysignal_lab.sqlite3`, `scan_results.json`, `refined_results.json`, caches, and equivalent generated outputs.
- `.env` is not read, modified, deleted, committed, or copied into evidence.
- Create or refresh docs for external API research, PRD-old compliance, runbook/README, safety boundary, and real Telegram QA.
- Use subagents during execution for disjoint worker lanes and final read-only review/QA gates; main thread integrates and resolves conflicts.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- No authenticated Polymarket CLOB order client or order auth flow.
- No private key, mnemonic, wallet secret, API secret generation, EIP-712 signing, real order create/cancel/submit, redeem, transfer, real sell, or CEX order path.
- No demo command, demo app module, randomized fake product runtime, or product docs that present demo as an accepted workflow.
- No non-PRD default strategy/assets such as `skew_mean_reversion`, DOGE, BNB, or HYPE.
- No hidden historical replay/backtest product surface beyond deterministic tests.
- No generated artifacts left as acceptance evidence unless placed under `.omo/evidence`.
- No reading `.env` to discover credentials. Real Telegram credentials must be explicitly exported by the operator or provided by the runtime environment.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: TDD/characterization-first where behavior changes or removals are risky; pytest for unit/integration; bounded CLI/curl/tmux-style real-surface checks for scheduler/dashboard/Telegram.
- Baseline capture before edits: `.venv/bin/python -m pytest -q`, `.venv/bin/python scripts/safety_scan.py src`, and `rg` checks for demo/non-PRD surfaces. Store output in `.omo/evidence/baseline-complete-prd-old-remove-demo.txt`.
- Per-task evidence: `.omo/evidence/task-N-complete-prd-old-remove-demo.txt` or `.json`, where `N` is the todo number.
- Final evidence: `.omo/evidence/final-complete-prd-old-remove-demo.txt`, `.omo/evidence/final-telegram-real-send-redacted.json`, `.omo/evidence/final-dashboard-smoke.json`, `.omo/evidence/final-live-market-smoke.json`.
- Required final commands:
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python scripts/safety_scan.py .`
  - `test ! -e src/polysignal_lab/app/demo.py && test ! -e src/polysignal_lab/app/demo_data.py`
  - `! rg "run_demo|demo_data|polysignal-demo|fake data|offline demo" src tests README.md docs pyproject.toml docker-entrypoint.sh`
  - `test ! -e logs && test ! -e state && test ! -e data/paper_trades.sqlite && test ! -e data/polysignal_lab.sqlite3 && test ! -e scan_results.json && test ! -e refined_results.json`
  - `test -e .env || true` without reading it.
  - `timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke` or the implemented equivalent bounded smoke command.
  - Real Telegram send command implemented by the worker, run with externally exported `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`, `dry_run=false`, and redacted output.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 0: Baseline, deletion manifest, docs skeleton, and test factories.
- Wave 1: Remove demo/product-scope contamination and harden safety/config defaults.
- Wave 2: Repair public market-data contracts and scheduler startup/subscription lifecycle.
- Wave 3: Align all three PRD strategies plus signal gate/Telegram startup validation.
- Wave 4: Complete paper fill/exit/settlement/report/storage/SQLite/dashboard final-scope behavior.
- Wave 5: CLI/Docker/docs/real-surface QA, including live read-only market smoke and real Telegram send.
- Wave 6: Parallel final review agents, manual QA executor, and main-thread integration fixes.

Subagent plan for execution:
- Worker A owns docs, deletion manifest, README/runbook, and generated artifact cleanup.
- Worker B owns config/safety/demo removal and test factory migration.
- Worker C owns market discovery, CLOB REST/WS, Binance WS, scheduler startup, and live smoke.
- Worker D owns strategy semantics and signal gate/formatter.
- Worker E owns paper simulator, settlement, reports, SQLite, dashboard.
- QA/review subagents are read-only after implementation and must not modify files.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | none | 2-20 | none |
| 2 | 1 | 3, 19 | 4, 5 |
| 3 | 1 | 4, 18, 19 | 2 |
| 4 | 1, 3 | 9-12 | 5 |
| 5 | 1 | 18, final safety | 4 |
| 6 | 1 | 7, 8, 18 | 9, 10, 11 |
| 7 | 6 | 8, 18 | 9, 10, 11 |
| 8 | 6, 7 | 14, 18 | 9, 10, 11 |
| 9 | 4, 6 | 12, 18 | 10, 11 |
| 10 | 4, 6 | 12, 18 | 9, 11 |
| 11 | 4, 6, 8 | 12, 18 | 9, 10 |
| 12 | 9, 10, 11 | 13, 18, real Telegram | 15, 16 |
| 13 | 12 | 14, 15 | 16, 17 |
| 14 | 8, 13 | 15, 16, 18 | 17 |
| 15 | 13, 14 | 16, 18 | 17 |
| 16 | 15 | 18 | 17 |
| 17 | 3, 5 | 18, 19 | 14, 15 |
| 18 | 6-17 | 19, final review | none |
| 19 | 2-18 | 20, final review | none |
| 20 | 18, 19 | final review | none |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Capture baseline, lock approved decisions, and build the PRD compliance ledger.
  What to do / Must NOT do: Record the current red/green state, create a PRD-old acceptance matrix that maps AC/SIM/SEC/success metrics to code/tests/docs, and include the owner decisions: full scope, generated-history deletion, docs creation, real Telegram channel send. Do not edit product behavior in this task.
  Parallelization: Wave 0 | Blocked by: none | Blocks: all todos
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:1-1183`, `.omo/drafts/complete-prd-old-remove-demo.md`, `tests/*`, `scripts/safety_scan.py`
  Acceptance criteria (agent-executable): `test -f docs/PRD_OLD_COMPLIANCE.md && rg "AC-006|SIM-|SEC-|Telegram|real channel|generated history" docs/PRD_OLD_COMPLIANCE.md && test -f .omo/evidence/baseline-complete-prd-old-remove-demo.txt`
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest -q | tee .omo/evidence/baseline-complete-prd-old-remove-demo.txt`; failure: search for unmapped PRD acceptance rows with `rg "AC-|SIM-|SEC-" docs/PRD-old.md` and verify each is represented in `docs/PRD_OLD_COMPLIANCE.md`. Evidence `.omo/evidence/task-1-complete-prd-old-remove-demo.txt`
  Commit: N | plan/baseline only unless execution policy requests commits

- [x] 2. Create external API research and deletion manifest docs before touching runtime.
  What to do / Must NOT do: Create `docs/EXTERNAL_API_RESEARCH.md` with official-source notes for Polymarket Gamma/CLOB public REST, Polymarket market WebSocket, Binance Spot WebSocket, Telegram `sendMessage`, and FastAPI static/API behavior; create `docs/GENERATED_HISTORY_DELETION.md` listing exact generated paths to delete and paths never to touch. Do not rely on third-party API claims and do not read `.env`.
  Parallelization: Wave 0 | Blocked by: 1 | Blocks: 3, 19
  References (executor has NO interview context - be exhaustive): Polymarket market-data overview, Polymarket authentication docs, Polymarket WSS market docs, Polymarket fetching-markets guide, Binance Spot WebSocket docs, Telegram Bot API `sendMessage`, FastAPI docs, `docs/PRD-old.md:154-170`, `docs/PRD-old.md:996-1047`
  Acceptance criteria (agent-executable): `test -f docs/EXTERNAL_API_RESEARCH.md && test -f docs/GENERATED_HISTORY_DELETION.md && rg "https://docs.polymarket.com|https://developers.binance.com|https://core.telegram.org/bots/api" docs/EXTERNAL_API_RESEARCH.md && rg "logs/|state/|data/paper_trades.sqlite|data/polysignal_lab.sqlite3|scan_results.json|refined_results.json|\\.env" docs/GENERATED_HISTORY_DELETION.md`
  QA scenarios (name the exact tool + invocation): happy: `rg "public|no auth|sendMessage|bookTicker|price_changes" docs/EXTERNAL_API_RESEARCH.md`; failure: `! rg "Medium|StackOverflow|blog" docs/EXTERNAL_API_RESEARCH.md`. Evidence `.omo/evidence/task-2-complete-prd-old-remove-demo.txt`
  Commit: N | docs: record external API research and deletion manifest

- [x] 3. Replace demo-backed fixtures with test-only factories, then remove demo runtime surfaces.
  What to do / Must NOT do: Add deterministic factories under `tests/`, update all tests away from `polysignal_lab.app.demo_data` and `run_demo`, then delete `src/polysignal_lab/app/demo.py`, `src/polysignal_lab/app/demo_data.py`, `polysignal-demo`, Docker `demo`, and demo docs. Do not keep product fake-data modules or rename demo code into product source.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 4, 18, 19
  References (executor has NO interview context - be exhaustive): `src/polysignal_lab/app/demo.py:1-230`, `src/polysignal_lab/app/demo_data.py:1-49`, `tests/conftest.py:1-40`, `tests/test_demo_e2e.py:1-12`, `pyproject.toml:26-29`, `docker-entrypoint.sh:7-30`, `README.md`, `docs/IMPLEMENTATION_SUMMARY.md`, `docs/TEST_RESULTS.md`
  Acceptance criteria (agent-executable): `test ! -e src/polysignal_lab/app/demo.py && test ! -e src/polysignal_lab/app/demo_data.py && ! rg "run_demo|demo_data|polysignal-demo|fake data|offline demo" src tests README.md docs pyproject.toml docker-entrypoint.sh`
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_orderbook_snapshot.py tests/test_paper_simulation.py -q`; failure: `python - <<'PY'\nimport importlib.util\nassert importlib.util.find_spec('polysignal_lab.app.demo') is None\nPY`. Evidence `.omo/evidence/task-3-complete-prd-old-remove-demo.txt`
  Commit: N | refactor(testing): remove demo runtime and move fixtures to tests

- [x] 4. Constrain config/schema/factory to PRD-old strategies and assets only.
  What to do / Must NOT do: Remove `skew_mean_reversion` from default runtime config/factory/docs and remove DOGE/BNB/HYPE defaults. Keep only VWAP Momentum, Late Consensus, PTB Diff. Decide `SPLIT` result state: remove it from PRD-facing settlement/report acceptance or isolate it so final states are strictly WIN/LOSS/VOID/UNKNOWN. Do not delete code unrelated to PRD alignment unless tests require it.
  Parallelization: Wave 1 | Blocked by: 1, 3 | Blocks: 9-12
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:203-333`, `docs/PRD-old.md:1029-1047`, `config/signal_bot.yaml:29`, `config/signal_bot.yaml:183-190`, `src/polysignal_lab/config.py:71-323`, `src/polysignal_lab/strategies/factory.py:1-25`, `src/polysignal_lab/strategies/skew_mean_reversion.py`, `src/polysignal_lab/domain/enums.py`, `src/polysignal_lab/paper/settlement.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_config.py tests/test_strategies.py -q && ! rg "skew_mean_reversion|DOGE|BNB|HYPE" config src README.md docs/PRD_OLD_COMPLIANCE.md`
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_config.py::test_strategy_factory_builds_only_prd_strategies -q`; failure: `.venv/bin/python -m pytest tests/test_config.py::test_non_prd_strategy_config_rejected -q && ! rg "skew_mean_reversion|DOGE|BNB|HYPE" config src README.md docs/PRD_OLD_COMPLIANCE.md`. Evidence `.omo/evidence/task-4-complete-prd-old-remove-demo.txt`
  Commit: N | refactor(scope): enforce PRD strategy and asset set

- [x] 5. Harden safety scan, ignore rules, and generated-history deletion.
  What to do / Must NOT do: Add ignore coverage for generated runtime artifacts including `.sqlite` and `.sqlite3`, fix `scripts/safety_scan.py .` to skip `.venv`, `.git`, generated data, caches, and `.env`, then delete approved generated history. Do not read `.env`; do not scan third-party virtualenv code as product source.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 18, final safety
  References (executor has NO interview context - be exhaustive): `scripts/safety_scan.py`, `.gitignore`, `docs/PRD-old.md:61-71`, `docs/PRD-old.md:108-119`, `docs/PRD-old.md:1010-1025`, deletion manifest: `logs/`, `state/`, `data/paper_trades.sqlite`, `data/polysignal_lab.sqlite3`, `scan_results.json`, `refined_results.json`
  Acceptance criteria (agent-executable): `.venv/bin/python scripts/safety_scan.py . && test ! -e logs && test ! -e state && test ! -e data/paper_trades.sqlite && test ! -e data/polysignal_lab.sqlite3 && test ! -e scan_results.json && test ! -e refined_results.json`
  QA scenarios (name the exact tool + invocation): happy: `git status --short --ignored | tee .omo/evidence/task-5-complete-prd-old-remove-demo.txt`; failure: create a temp fixture under `.omo/tmp-safety` containing `create_order` in product-like path and assert safety scan fails, then remove temp fixture. Evidence `.omo/evidence/task-5-complete-prd-old-remove-demo.txt`
  Commit: N | chore(safety): delete generated history and harden scan scope

- [x] 6. Repair scheduler startup order and subscription lifecycle.
  What to do / Must NOT do: Ensure startup follows PRD startup order: load config, validate Telegram settings when publishing is enabled, load assets/strategies, init wallet, discover markets, then start Polymarket market WS and Binance spot WS. Add resubscribe behavior when market token set changes and prevent empty Polymarket subscriptions. Do not add authenticated market clients.
  Parallelization: Wave 2 | Blocked by: 1 | Blocks: 7, 8, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:154-170`, `src/polysignal_lab/app/scheduler.py:136-288`, `src/polysignal_lab/app/scheduler.py:587-604`, `src/polysignal_lab/app/scheduler.py:689`, `src/polysignal_lab/data/*`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_market_data.py -q` with tests asserting discovery precedes WebSocket subscription and subscription receives non-empty token ids.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_scheduler.py::test_refresh_markets_before_starting_streams tests/test_scheduler.py::test_market_ws_subscribes_after_token_discovery -q`; failure: `.venv/bin/python -m pytest tests/test_scheduler.py::test_empty_market_refresh_does_not_subscribe_market_ws -q`. Evidence `.omo/evidence/task-6-complete-prd-old-remove-demo.txt`
  Commit: N | fix(scheduler): discover markets before streaming subscriptions

- [x] 7. Align Polymarket/Binance data contracts to official public APIs.
  What to do / Must NOT do: Update Gamma active market discovery/pagination/filtering, CLOB book/mid/spread parsing, Polymarket market WS `price_changes`/book/best_bid_ask/last_trade/lifecycle handling, and Binance `<symbol>@bookTicker` spot updates. Add official-payload fixtures. Do not send auth headers or use trading endpoints.
  Parallelization: Wave 2 | Blocked by: 6 | Blocks: 8, 18
  References (executor has NO interview context - be exhaustive): `src/polysignal_lab/data/polymarket_market_discovery.py:71-81`, `src/polysignal_lab/data/polymarket_clob_ws.py:62-80`, `src/polysignal_lab/data/binance_spot_ws.py:1-68`, `docs/EXTERNAL_API_RESEARCH.md`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_market_data.py tests/test_websocket_contracts.py -q` and `! rg "Authorization|private_key|create_order|cancel_order" src/polysignal_lab/data src/polysignal_lab/app`
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_polymarket_price_changes_event_updates_registry tests/test_websocket_contracts.py::test_binance_bookticker_updates_spot_registry -q`; failure: `.venv/bin/python -m pytest tests/test_websocket_contracts.py::test_malformed_public_market_events_are_ignored_without_crash -q`. Evidence `.omo/evidence/task-7-complete-prd-old-remove-demo.txt`
  Commit: N | fix(data): match public Polymarket and Binance contracts

- [x] 8. Parse PTB/resolution metadata and normalized snapshots correctly.
  What to do / Must NOT do: Make `Market.from_gamma()` and scheduler updates populate `price_to_beat`, active/resolved/closed status, market time window, token mapping, and `resolved_outcome` for WIN/LOSS/VOID/UNKNOWN. Keep PRD result states strict; remove or isolate `SPLIT` from final PRD acceptance. Do not infer real outcomes from non-authoritative text when official fields exist.
  Parallelization: Wave 2 | Blocked by: 6, 7 | Blocks: 11, 14, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:187-201`, `docs/PRD-old.md:312-333`, `src/polysignal_lab/domain/market.py:48-107`, `src/polysignal_lab/app/scheduler.py:190-205`, `src/polysignal_lab/app/scheduler.py:440-456`, `src/polysignal_lab/paper/settlement.py:15-60`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_market_parsing.py tests/test_settlement.py -q` with explicit WIN/LOSS/VOID/UNKNOWN cases and no PRD-facing `SPLIT` result.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_market_parsing.py::test_gamma_resolved_payload_sets_resolved_outcome tests/test_settlement.py::test_resolved_up_and_down_positions_settle_win_loss -q`; failure: `.venv/bin/python -m pytest tests/test_settlement.py::test_missing_resolved_outcome_stays_unknown_and_retriable -q`. Evidence `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
  Commit: N | fix(domain): parse PTB and resolution outcomes

- [x] 9. Implement VWAP Momentum PRD semantics.
  What to do / Must NOT do: Add/repair VWAP Momentum config and evaluation for VWAP, deviation, momentum, z_score, favorite side, spread, target ask range, time window, orderbook freshness, and reason/metric output. Do not use fake/demo market data in product tests.
  Parallelization: Wave 3 | Blocked by: 4, 6 | Blocks: 12, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:203-253`, `docs/PRD-old.md:884-899`, `src/polysignal_lab/strategies/base.py:62-69`, `src/polysignal_lab/strategies/vwap_momentum.py:197-260`, `src/polysignal_lab/config.py:193-210`, `tests/test_strategies.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_vwap_momentum.py tests/test_strategies.py -q` with accept/reject tests for z_score, momentum mismatch, stale book, wide spread, and entry window.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_emits_buy_up_and_down_with_z_score -q`; failure: `.venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_rejects_below_z_score_threshold tests/test_vwap_momentum.py::test_vwap_momentum_rejects_stale_or_wide_spread_book -q`. Evidence `.omo/evidence/task-9-complete-prd-old-remove-demo.txt`
  Commit: N | feat(strategy): align VWAP Momentum with PRD

- [x] 10. Implement Late Consensus PRD semantics.
  What to do / Must NOT do: Enforce ask_sum, confidence_abs, favorite side, max_entry_price, max_spread, freshness, seconds-to-close window, flip guard, and Binance spot movement/freshness where required by PRD inputs/rules. Do not include DOGE/BNB/HYPE.
  Parallelization: Wave 3 | Blocked by: 4, 6 | Blocks: 12, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:254-295`, `docs/PRD-old.md:901-913`, `src/polysignal_lab/strategies/late_consensus.py:40-187`, `src/polysignal_lab/config.py`, `tests/test_strategies.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_late_consensus.py tests/test_strategies.py -q` with BTC/ETH/SOL/XRP coverage, max_spread rejects, confidence rejects, flip guard, and stale spot rejects.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_late_consensus.py::test_late_consensus_emits_multi_asset_signal_with_metrics -q`; failure: `.venv/bin/python -m pytest tests/test_late_consensus.py::test_late_consensus_rejects_wide_spread tests/test_late_consensus.py::test_late_consensus_rejects_stale_spot_or_flip_guard -q`. Evidence `.omo/evidence/task-10-complete-prd-old-remove-demo.txt`
  Commit: N | feat(strategy): align Late Consensus with PRD

- [x] 11. Implement PTB Diff PRD trigger schema and probability-edge logic.
  What to do / Must NOT do: Replace `min_prob/max_prob`-style runtime semantics with PRD trigger rows using `min_diff_usd`, `max_token_price`, `min_probability_edge`, and seconds-to-close windows for above/below PTB scenarios. Keep BTC-focused PTB behavior. Do not change to real trading.
  Parallelization: Wave 3 | Blocked by: 4, 6, 8 | Blocks: 12, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:296-333`, `docs/PRD-old.md:914-930`, `src/polysignal_lab/strategies/ptb_diff.py:89-169`, `src/polysignal_lab/config.py`, `tests/test_strategies.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_ptb_diff.py tests/test_strategies.py -q` with BUY_UP/BUY_DOWN accepts and rejects for token price, probability edge, diff, and time window.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_emits_buy_up_and_down_from_trigger_rows -q`; failure: `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_rejects_above_max_token_price tests/test_ptb_diff.py::test_ptb_diff_rejects_below_probability_edge -q`. Evidence `.omo/evidence/task-11-complete-prd-old-remove-demo.txt`
  Commit: N | feat(strategy): align PTB Diff triggers with PRD

- [x] 12. Complete signal gate, formatter, Telegram publisher validation, dedupe, and real-send path.
  What to do / Must NOT do: Enforce gate/dedupe/rate limits and PRD reason fields; format signal/result/daily messages with non-guarantee language; validate Telegram bot token/channel id at startup when publishing is enabled; redact tokens in logs/errors; support dry-run tests and a real `sendMessage` QA command. Do not read `.env`; real credentials must come from exported env vars or explicit runtime config.
  Parallelization: Wave 3 | Blocked by: 9, 10, 11 | Blocks: 13, 18, 20
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:374-442`, `docs/PRD-old.md:996-1047`, `src/polysignal_lab/signal_layer/*`, `src/polysignal_lab/publish/telegram_publisher.py:1-60`, `src/polysignal_lab/app/scheduler.py:344-383`, `src/polysignal_lab/app/scheduler.py:689`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_signal_gate.py tests/test_storage_reporting_publish.py tests/test_telegram_validation.py -q` and a script/CLI exists for real Telegram send that records redacted evidence.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_telegram_validation.py::test_mocked_telegram_send_returns_sent_and_redacts_token tests/test_signal_gate.py::test_signal_deduper_prevents_duplicate_channel_publish -q`; failure: `env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m pytest tests/test_telegram_validation.py::test_missing_telegram_credentials_fail_startup_when_publish_enabled -q`. Evidence `.omo/evidence/task-12-complete-prd-old-remove-demo.txt`
  Commit: N | feat(telegram): validate and publish PRD messages safely

- [x] 13. Complete paper simulator fills, wallet, exposure, and stale-fill rejection.
  What to do / Must NOT do: Ensure accepted/published signals create paper orders, simulate taker fills from best ask/orderbook depth, reject stale/missing/insufficient-depth fills, update cash/equity/open positions/exposure, and log all fill decisions. Do not add real order placement.
  Parallelization: Wave 4 | Blocked by: 12 | Blocks: 14, 15
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:187-201`, `docs/PRD-old.md:443-535`, `docs/PRD-old.md:1168-1176`, `src/polysignal_lab/paper/*`, `src/polysignal_lab/app/scheduler.py:384-438`, `tests/test_paper_simulation.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_paper_simulation.py tests/test_scheduler_paper.py -q` with stale paper fill count = 0 in report metrics.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_accepted_signal_fills_at_best_ask_and_updates_wallet -q`; failure: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_stale_orderbook_rejects_fill_without_position tests/test_scheduler_paper.py::test_stale_paper_fill_count_is_zero -q`. Evidence `.omo/evidence/task-13-complete-prd-old-remove-demo.txt`
  Commit: N | feat(paper): complete fill and wallet lifecycle

- [x] 14. Wire paper TP/SL/max-hold exits, settlement, daily reports, and PRD result states.
  What to do / Must NOT do: Call the paper exit engine from scheduler/runtime, implement take-profit, stop-loss, max-hold, hold-to-resolution, WIN/LOSS/VOID/UNKNOWN classification, Telegram paper result, and daily paper report metrics. Remove or isolate `SPLIT` from PRD-facing outputs. Do not make paper exit a real sell.
  Parallelization: Wave 4 | Blocked by: 8, 13 | Blocks: 15, 16, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:194-201`, `docs/PRD-old.md:602-690`, `docs/PRD-old.md:1004`, `docs/PRD-old.md:1122`, `docs/PRD-old.md:1176`, `src/polysignal_lab/paper/exit_engine.py:1-120`, `src/polysignal_lab/paper/settlement.py:1-70`, `src/polysignal_lab/paper/report.py`, `src/polysignal_lab/storage/sqlite_store.py`, `src/polysignal_lab/app/scheduler.py:440-565`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_exit_engine.py tests/test_settlement.py tests/test_reporting.py tests/test_scheduler_reports.py -q` with daily report Telegram publish records and only WIN/LOSS/VOID/UNKNOWN result states.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_exit_engine.py::test_take_profit_stop_loss_and_max_hold_exits tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -q`; failure: `.venv/bin/python -m pytest tests/test_settlement.py::test_unknown_outcome_does_not_inflate_win_rate tests/test_scheduler_reports.py::test_daily_report_publish_record_written -q`. Evidence `.omo/evidence/task-14-complete-prd-old-remove-demo.txt`
  Commit: N | feat(paper): wire exits settlement and reports

- [x] 15. Make storage/SQLite/audit logs complete and restorable.
  What to do / Must NOT do: Ensure JSONL and SQLite persist signals, rejected signals, paper orders/fills/positions/results, wallet snapshots, reports, Telegram publishes, and system events. Add migrations/schema checks and temp-dir tests. Do not write runtime databases into the repo during tests.
  Parallelization: Wave 4 | Blocked by: 13, 14 | Blocks: 16, 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:691-731`, `docs/PRD-old.md:738-826`, `src/polysignal_lab/storage/sqlite_store.py:1-280`, `src/polysignal_lab/observability/*`, `tests/test_storage_reporting_publish.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py tests/test_storage_restore.py -q` and `! find data -maxdepth 1 \\( -name '*.sqlite' -o -name '*.sqlite3' \\) -print | rg .`
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_storage_restore.py::test_sqlite_store_restores_wallet_reports_and_leaderboard -q`; failure: `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py::test_schema_rejects_missing_required_columns tests/test_storage_reporting_publish.py::test_duplicate_ids_are_idempotent_or_reported -q`. Evidence `.omo/evidence/task-15-complete-prd-old-remove-demo.txt`
  Commit: N | feat(storage): persist PRD audit lifecycle

- [x] 16. Complete read-only dashboard APIs and leaderboard from real stored data.
  What to do / Must NOT do: Ensure dashboard serves `/health`, `/api/overview`, `/api/signals`, `/api/rejected-signals`, `/api/positions`, `/api/trades`, `/api/leaderboard`, and `/` HTML from storage. Keep all routes read-only. Do not add write/admin/trading actions.
  Parallelization: Wave 4 | Blocked by: 15 | Blocks: 18
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:751-826`, `docs/PRD-old.md:1161-1164`, `src/polysignal_lab/dashboard/app.py`, `tests/test_dashboard.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest tests/test_dashboard.py -q` and endpoint smoke against a temp populated SQLite store returns non-empty overview and leaderboard rows.
  QA scenarios (name the exact tool + invocation): happy: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data tests/test_dashboard.py::test_leaderboard_uses_sqlite_report_data -q`; failure: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_rejects_write_methods -q`. Evidence `.omo/evidence/task-16-complete-prd-old-remove-demo.txt`
  Commit: N | feat(dashboard): expose read-only PRD views

- [x] 17. Update CLI, Docker, packaging, and runtime modes.
  What to do / Must NOT do: Keep supported modes to scheduler, dashboard, test, shell, and any bounded smoke command. Remove demo from CLI/Docker/docs. Ensure Docker test mode does not perform ad hoc network installs when dependencies are already packaged, or document/build accordingly. Do not add demo aliases.
  Parallelization: Wave 5 | Blocked by: 3, 5 | Blocks: 18, 19
  References (executor has NO interview context - be exhaustive): `pyproject.toml:26-29`, `docker-entrypoint.sh:7-30`, `Dockerfile`, `README.md`, `src/polysignal_lab/app/main.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m polysignal_lab.app.main --help >/tmp/polysignal-help.txt && ! rg "demo|polysignal-demo" pyproject.toml docker-entrypoint.sh README.md docs src`
  QA scenarios (name the exact tool + invocation): happy: `docker build -t polysignal-lab:prd-old .` if Docker is available; failure: `docker run polysignal-lab:prd-old demo` fails with usage and no demo execution. Evidence `.omo/evidence/task-17-complete-prd-old-remove-demo.txt`
  Commit: N | chore(runtime): remove demo modes from packaging

- [x] 18. Run bounded real-surface integration QA for market data, scheduler, dashboard, and safety.
  What to do / Must NOT do: Add or run deterministic local fake-public-API integration plus bounded live read-only smoke: Gamma active events, CLOB book/404 behavior, Binance spot stream or REST fallback, scheduler snapshot creation after discovery, dashboard endpoint reads, and project safety scan. Do not hit authenticated/trading endpoints.
  Parallelization: Wave 5 | Blocked by: 6-17 | Blocks: 19, final review
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:1029-1074`, `docs/EXTERNAL_API_RESEARCH.md`, `src/polysignal_lab/app/main.py`, `src/polysignal_lab/app/scheduler.py`, `src/polysignal_lab/dashboard/app.py`, `scripts/safety_scan.py`
  Acceptance criteria (agent-executable): `.venv/bin/python -m pytest -q && .venv/bin/python scripts/safety_scan.py . && timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke` or implemented equivalent.
  QA scenarios (name the exact tool + invocation): happy: `mkdir -p .omo/evidence && curl -fsS "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=3" >/tmp/polysignal-gamma-smoke.json && timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke.json`; failure: `.venv/bin/python -m pytest tests/test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception -q`. Evidence `.omo/evidence/task-18-complete-prd-old-remove-demo.txt`
  Commit: N | test(integration): prove live read-only surfaces

- [x] 19. Refresh README/runbooks/compliance docs and remove stale demo claims.
  What to do / Must NOT do: Update `README.md`, implementation/compliance docs, test results, and runbooks to describe real scheduler, dashboard, safety scan, generated-history deletion, Telegram credentials, real-send QA, and PRD-old compliance. Remove or rewrite old demo-delivered claims. Do not document any forbidden trading setup.
  Parallelization: Wave 5 | Blocked by: 2-18 | Blocks: 20, final review
  References (executor has NO interview context - be exhaustive): `README.md`, `docs/IMPLEMENTATION_SUMMARY.md`, `docs/TEST_RESULTS.md`, `docs/PRD_OLD_COMPLIANCE.md`, `docs/EXTERNAL_API_RESEARCH.md`, `docs/GENERATED_HISTORY_DELETION.md`, `docs/PRD-old.md`
  Acceptance criteria (agent-executable): `rg "PRD-old|real Telegram|safety_scan.py|scheduler|dashboard|generated history" README.md docs && ! rg "offline demo|fake data|demo run|polysignal-demo" README.md docs`
  QA scenarios (name the exact tool + invocation): happy: `rg "PRD-old|real Telegram|safety_scan.py|scheduler|dashboard|generated history" README.md docs | tee .omo/evidence/task-19-complete-prd-old-remove-demo.txt`; failure: `! rg "offline demo|fake data|demo run|polysignal-demo|PRIVATE_KEY|create_order|redeem" README.md docs`. Evidence `.omo/evidence/task-19-complete-prd-old-remove-demo.txt`
  Commit: N | docs: document PRD-old complete runtime

- [ ] 20. Execute mandatory real Telegram channel send with redacted evidence.
  What to do / Must NOT do: With externally supplied `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`, run the implemented real-send QA path using `dry_run=false` and a formatted PRD signal/test message that clearly says it is a system test/non-guarantee signal. Persist publish status, non-empty Telegram message id, timestamp, and redacted token/channel in `.omo/evidence/final-telegram-real-send-redacted.json`. Do not read `.env`, print full token, or commit credentials.
  Parallelization: Wave 5 | Blocked by: 12, 18, 19 | Blocks: final review
  References (executor has NO interview context - be exhaustive): `docs/PRD-old.md:54`, `docs/PRD-old.md:159`, `docs/PRD-old.md:374-442`, `docs/PRD-old.md:996-1047`, `src/polysignal_lab/publish/telegram_publisher.py`
  Acceptance criteria (agent-executable): `test -s .omo/evidence/final-telegram-real-send-redacted.json && rg '"status": "SENT"|"message_id":' .omo/evidence/final-telegram-real-send-redacted.json && ! rg 'bot[0-9]+:|TELEGRAM_BOT_TOKEN|TELEGRAM_CHANNEL_ID' .omo/evidence/final-telegram-real-send-redacted.json && python - <<'PY'\nimport os, pathlib\np = pathlib.Path('.omo/evidence/final-telegram-real-send-redacted.json')\ntext = p.read_text()\nfor name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID'):\n    value = os.environ.get(name)\n    assert value, f'{name} must be exported for real-send acceptance'\n    assert value not in text, f'{name} raw value leaked into evidence'\nPY`
  QA scenarios (name the exact tool + invocation): happy: `test -n "${TELEGRAM_BOT_TOKEN:-}" && test -n "${TELEGRAM_CHANNEL_ID:-}" && .venv/bin/python -m polysignal_lab.tools.telegram_real_send --config config/signal_bot.yaml --evidence .omo/evidence/final-telegram-real-send-redacted.json`; failure: `env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHANNEL_ID .venv/bin/python -m polysignal_lab.tools.telegram_real_send --config config/signal_bot.yaml --evidence /tmp/should-not-send.json` must fail before network call with a redacted error. Evidence `.omo/evidence/task-20-complete-prd-old-remove-demo.txt`
  Commit: N | test(telegram): record real channel send evidence

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
  Read-only Momus or gate-reviewer checks every todo, PRD-old AC/SIM/SEC row, and owner decision against code/docs/evidence. Must return APPROVE or concrete blocking findings.
- [ ] F2. Code quality review
  Read-only code reviewer checks diffs, safety boundary, secret handling, error paths, async scheduler lifecycle, and tests. Must explicitly search for forbidden trading/auth terms and demo surfaces.
- [ ] F3. Real manual QA
  QA executor runs the final commands, dashboard smoke, bounded live read-only market smoke, Docker smoke if available, and real Telegram send evidence validation. Must attach artifact paths.
- [ ] F4. Scope fidelity
  Independent reviewer verifies PRD-old final scope only: no extra default strategies/assets, no demo runtime, no missing section 26 consensus/SQLite/daily report/dashboard/leaderboard/TP-SL behavior, and no `.env` inspection.

## Commit strategy
- User did not request commits. Default execution should leave working-tree changes unstaged unless the user later asks for commits.
- If commits are requested later, use atomic commits by wave:
  - `docs(research): record PRD-old external API and compliance scope`
  - `refactor(testing): remove demo runtime and move fixtures to tests`
  - `refactor(scope): enforce PRD strategy and asset defaults`
  - `fix(data): repair public market data and scheduler startup`
  - `feat(strategy): align PRD strategy semantics`
  - `feat(paper): complete paper lifecycle reports and storage`
  - `feat(dashboard): expose read-only PRD views`
  - `test(qa): add real-surface PRD verification evidence`

## Success criteria
- `docs/PRD-old.md` final scope is implemented or explicitly documented as verified with no open gaps.
- `pytest -q` is green.
- `scripts/safety_scan.py .` passes without scanning `.venv` or reading `.env`.
- Demo runtime/source/CLI/Docker/docs claims are gone; test-only factories remain only under `tests/`.
- Generated historical artifacts approved for deletion are absent; `.env` remains untouched if present.
- Default runtime has only PRD strategies/assets.
- Scheduler discovers markets before Polymarket WS subscription and never subscribes empty token sets.
- Polymarket/Binance parsing is backed by official-contract tests and bounded live read-only smoke.
- VWAP Momentum, Late Consensus, and PTB Diff pass PRD trigger accept/reject tests.
- Telegram startup validation, formatting, dedupe, redaction, dry-run tests, and real-channel send evidence all pass.
- Paper fills, TP/SL/max-hold, settlement, daily reports, SQLite persistence, dashboard, consensus, and leaderboard are verified from stored data.
- Final parallel reviewers approve or all blocking findings are fixed before declaring implementation complete.
