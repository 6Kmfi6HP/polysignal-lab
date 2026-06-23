# PRD-old Compliance Ledger

Source of truth: `docs/PRD-old.md`.

This ledger is the current acceptance document for the PRD-old completion work. It maps every PRD-old acceptance row, plus the success metrics in section 27, to code, tests, docs, and evidence. Todo 19 refreshes documentation only and does not change product behavior.

## Locked Owner Decisions

| Decision | Locked scope |
| --- | --- |
| Full scope | Complete PRD-old final scope, including section 26: Late Consensus, BTC/ETH/SOL/XRP, consensus, SQLite, daily report, paper TP/SL, dashboard, and strategy leaderboard. |
| Generated history | Delete generated history during execution after a deletion manifest is created: `logs/`, `state/`, `data/paper_trades.sqlite`, `data/polysignal_lab.sqlite3`, `scan_results.json`, `refined_results.json`, caches, and equivalent generated outputs. Preserve `.env` untouched and unread. |
| Docs creation | Create or refresh PRD-old compliance, external API research, generated-history deletion, runbook/README, safety-boundary, and real Telegram QA docs. |
| Telegram acceptance | A real channel send is required for final acceptance when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` are supplied externally. Evidence must redact token and channel identifiers. |

## Current State

| Scenario | Invocation | Binary observable | Artifact |
| --- | --- | --- | --- |
| Full current suite | `.venv/bin/python -m pytest -q` | Exit 0; 120 tests passed with one existing FastAPI/Starlette deprecation warning. | `.omo/evidence/task-18-complete-prd-old-remove-demo.txt` |
| Whole-repo safety scan | `.venv/bin/python scripts/safety_scan.py .` | Exit 0; `Safety scan passed`. | `.omo/evidence/task-18-complete-prd-old-remove-demo.txt` |
| Live bounded smoke | `timeout 120 .venv/bin/python -m polysignal_lab.app.main --config config/signal_bot.yaml --once --real-readonly-smoke --evidence .omo/evidence/final-live-market-smoke.json` | Exit 0; `Bounded read-only smoke passed`; JSON has `passed=true` and `failure_count=0`. | `.omo/evidence/final-live-market-smoke.json` |
| real Telegram QA path | `.venv/bin/python -m polysignal_lab.publish.telegram_qa --live --evidence .omo/evidence/final-telegram-real-send-redacted.json` | Implemented; without exported credentials it exits 2 and writes redacted `TELEGRAM_NOT_CONFIGURED` evidence. | `.omo/evidence/todo-12-telegram-real-send-redacted.json` |

Live bounded smoke performs public Gamma `/events`, public CLOB `/book`, expected public CLOB 404, Binance public REST fallback, scheduler snapshot, dashboard reads, and safety scan. If Gamma `limit=3` lacks configured crypto Up/Down markets, evidence records the public fallback-market detail; deterministic tests cover the configured BTC Up/Down path.

## Functional Acceptance Matrix

| ID | PRD-old requirement | Code surface | Tests / commands | Docs / evidence | Current status |
| --- | --- | --- | --- | --- | --- |
| AC-001 | Service starts without wallet secret material. | `src/polysignal_lab/config.py`, `src/polysignal_lab/app/main.py`, `src/polysignal_lab/app/scheduler.py` | `tests/test_config_security.py::test_settings_load_without_secret_key_material`; live bounded smoke. | `docs/PRD-old.md`, `.omo/evidence/final-live-market-smoke.json` | Complete; runtime smoke exits 0. |
| AC-002 | Discover current BTC 5m/15m market cache non-empty. | `src/polysignal_lab/data/polymarket_market_discovery.py`, `src/polysignal_lab/app/scheduler.py` | `tests/test_market_discovery_and_feeds.py::test_market_discovery_flattens_and_parses_crypto_updown`; live bounded smoke. | `docs/PRD-old.md`, `.omo/evidence/final-live-market-smoke.json` | Complete for deterministic BTC Up/Down tests; live smoke records fallback detail when bounded Gamma page lacks configured markets. |
| AC-003 | Receive orderbook with continuously updated best bid/ask. | `src/polysignal_lab/data/polymarket_clob_ws.py`, `src/polysignal_lab/data/polymarket_clob_rest.py`, `src/polysignal_lab/domain/orderbook.py`, `src/polysignal_lab/data/state.py` | `tests/test_market_discovery_and_feeds.py::test_polymarket_ws_book_message_updates_registry`, `tests/test_orderbook_snapshot.py`, live bounded smoke. | `docs/PRD-old.md`, `.omo/evidence/final-live-market-smoke.json` | Complete. |
| AC-004 | Receive Binance spot updates. | `src/polysignal_lab/data/binance_spot_ws.py`, `src/polysignal_lab/data/state.py` | `tests/test_market_discovery_and_feeds.py::test_binance_feed_url_and_parse_message`, `tests/test_websocket_contracts.py`, live bounded smoke. | `docs/PRD-old.md`, `.omo/evidence/final-live-market-smoke.json` | Complete. |
| AC-005 | At least one strategy outputs `SignalCandidate`. | `src/polysignal_lab/strategies/ptb_diff.py`, `src/polysignal_lab/strategies/late_consensus.py`, `src/polysignal_lab/strategies/vwap_momentum.py`, `src/polysignal_lab/strategies/factory.py` | `tests/test_strategies.py`, strategy-specific tests. | `docs/PRD-old.md`, task 9-11 evidence | Complete. |
| AC-006 | Send Telegram formatted signal to channel. | `src/polysignal_lab/publish/telegram_publisher.py`, `src/polysignal_lab/publish/telegram_qa.py`, `src/polysignal_lab/signal_layer/formatter.py`, `src/polysignal_lab/app/scheduler.py` | `tests/test_storage_reporting_publish.py::test_telegram_dry_run_publish`, formatter tests, real Telegram QA command. | `docs/PRD-old.md`, `.omo/evidence/todo-12-telegram-real-send-redacted.json` | Complete path; real send requires externally exported credentials and records redacted evidence. |
| AC-007 | Create paper order after signal publish. | `src/polysignal_lab/paper/simulator.py`, `src/polysignal_lab/domain/paper_order.py`, `src/polysignal_lab/app/scheduler.py` | `tests/test_paper_simulation.py::test_paper_fill_wallet_position`, scheduler paper tests. | `docs/PRD-old.md`, task 13 evidence | Complete. |
| AC-008 | Create paper fill when fill model allows it. | `src/polysignal_lab/paper/fill_model.py`, `src/polysignal_lab/paper/simulator.py` | `tests/test_paper_simulation.py::test_paper_fill_wallet_position` | `docs/PRD-old.md`, task 13 evidence | Complete. |
| AC-009 | Create open position after fill. | `src/polysignal_lab/domain/paper_position.py`, `src/polysignal_lab/paper/wallet.py`, `src/polysignal_lab/paper/simulator.py`, `src/polysignal_lab/storage/sqlite_store.py` | `tests/test_paper_simulation.py::test_paper_fill_wallet_position`, dashboard/store tests | `docs/PRD-old.md`, task 13-16 evidence | Complete. |
| AC-010 | Settle resolved market position to WIN/LOSS/VOID. | `src/polysignal_lab/paper/settlement.py`, `src/polysignal_lab/domain/market.py`, `src/polysignal_lab/domain/enums.py`, `src/polysignal_lab/app/scheduler.py` | `tests/test_paper_simulation.py::test_settlement_win_and_loss`; `tests/test_config.py::test_prd_result_states_exclude_partial_settlement`. | `docs/PRD-old.md:1034` | PRD-facing settlement states are strict: WIN/LOSS/VOID/UNKNOWN. |
| AC-011 | Daily report includes win rate. | `src/polysignal_lab/paper/report.py`, `src/polysignal_lab/app/scheduler.py`, `src/polysignal_lab/storage/sqlite_store.py`, `src/polysignal_lab/dashboard/app.py` | `tests/test_storage_reporting_publish.py::test_report_calculates_daily_metrics`, scheduler daily report tests. | `docs/PRD-old.md`, task 14-16 evidence | Complete. |
| AC-012 | Daily report includes paper PnL and equity. | `src/polysignal_lab/paper/report.py`, `src/polysignal_lab/paper/wallet.py`, `src/polysignal_lab/storage/sqlite_store.py`, `src/polysignal_lab/dashboard/app.py` | `tests/test_storage_reporting_publish.py::test_report_calculates_daily_metrics`, report persistence tests. | `docs/PRD-old.md`, task 14-16 evidence | Complete. |

## Safety Acceptance Matrix

| ID | PRD-old requirement | Code surface | Tests / commands | Docs / evidence | Current status |
| --- | --- | --- | --- | --- | --- |
| SEC-001 | No real order-placement path. | `src/polysignal_lab/observability/safety.py`, `scripts/safety_scan.py`, product source tree | `tests/test_safety.py`, `.venv/bin/python scripts/safety_scan.py .`, final forbidden-term safety check | `docs/PRD-old.md` | Complete; whole-repo scan passes. |
| SEC-002 | No real cancellation path. | `src/polysignal_lab/observability/safety.py`, `scripts/safety_scan.py`, product source tree | `tests/test_safety.py`, final forbidden-term safety check | `docs/PRD-old.md` | Complete; whole-repo scan passes. |
| SEC-003 | No wallet secret material; config schema rejects sensitive key material. | `src/polysignal_lab/config.py` | `tests/test_config_security.py::test_settings_rejects_sensitive_env_key`, `tests/test_config_security.py::test_safety_flags_cannot_be_enabled` | `docs/PRD-old.md` | Complete; `.env` remains out of scope and unread. |
| SEC-004 | No chain payout claim module. | `src/polysignal_lab/observability/safety.py`, product source tree | safety scan and final forbidden-term check | `docs/PRD-old.md` | Complete. |
| SEC-005 | No real sell execution. | `src/polysignal_lab/observability/safety.py`, paper-only exit/settlement modules | safety scan and final forbidden-term check | `docs/PRD-old.md` | Complete. |
| SEC-006 | Telegram token does not leak. | `src/polysignal_lab/publish/telegram_publisher.py`, `src/polysignal_lab/publish/telegram_qa.py`, `src/polysignal_lab/utils.py`, observability/logging | Telegram validation/redaction tests and real Telegram redacted evidence path | `docs/PRD-old.md`, `.omo/evidence/todo-12-telegram-real-send-redacted.json` | Complete. |

## Simulation Acceptance Matrix

| ID | PRD-old requirement | Code surface | Tests / commands | Docs / evidence | Current status |
| --- | --- | --- | --- | --- | --- |
| SIM-001 | Paper wallet cash decreases after fill. | `src/polysignal_lab/paper/wallet.py`, `src/polysignal_lab/paper/simulator.py` | `tests/test_paper_simulation.py::test_paper_fill_wallet_position` | `docs/PRD-old.md`, task 13 evidence | Complete. |
| SIM-002 | Shares equal `stake / fill_price`. | `src/polysignal_lab/paper/fill_model.py`, `src/polysignal_lab/paper/simulator.py` | `tests/test_paper_simulation.py::test_paper_fill_wallet_position` | `docs/PRD-old.md`, task 13 evidence | Complete. |
| SIM-003 | WIN settlement equals shares. | `src/polysignal_lab/paper/settlement.py`, `src/polysignal_lab/domain/paper_result.py` | `tests/test_paper_simulation.py::test_settlement_win_and_loss` | `docs/PRD-old.md`, task 14 evidence | Complete. |
| SIM-004 | LOSS settlement equals 0. | `src/polysignal_lab/paper/settlement.py`, `src/polysignal_lab/domain/paper_result.py` | settlement tests. | `docs/PRD-old.md`, task 14 evidence | Complete. |
| SIM-005 | PnL equals settlement minus stake. | `src/polysignal_lab/paper/settlement.py`, `src/polysignal_lab/paper/exit_engine.py`, `src/polysignal_lab/paper/report.py` | settlement and report tests. | `docs/PRD-old.md`, task 14 evidence | Complete. |
| SIM-006 | Stale book rejects paper fill. | `src/polysignal_lab/domain/orderbook.py`, `src/polysignal_lab/paper/fill_model.py`, `src/polysignal_lab/paper/simulator.py` | `tests/test_orderbook_snapshot.py::test_staleness_detection`, paper stale-fill rejection tests. | `docs/PRD-old.md`, task 13 evidence | Complete. |
| SIM-007 | Ask above max entry rejects paper fill. | `src/polysignal_lab/paper/fill_model.py`, `src/polysignal_lab/paper/simulator.py` | `tests/test_paper_simulation.py::test_paper_rejects_ask_above_max` | `docs/PRD-old.md`, task 13 evidence | Complete. |
| SIM-008 | Insufficient cash rejects paper fill. | `src/polysignal_lab/paper/wallet.py`, `src/polysignal_lab/paper/simulator.py` | `tests/test_paper_simulation.py::test_paper_rejects_insufficient_cash` | `docs/PRD-old.md`, task 13 evidence | Complete. |
| SIM-009 | Paper result written to `paper_results.jsonl` with complete record. | `src/polysignal_lab/storage/jsonl_store.py`, `src/polysignal_lab/app/scheduler.py`, `src/polysignal_lab/storage/sqlite_store.py` | `tests/test_storage_reporting_publish.py::test_jsonl_and_state_store`, scheduler settlement/report persistence tests. | `docs/PRD-old.md`, task 14-15 evidence | Complete. |

## Success Metrics Matrix

| Metric ID | PRD-old success metric | Code / tests / evidence mapping | Current status |
| --- | --- | --- | --- |
| SM-001 | Live execution path count = 0. | `scripts/safety_scan.py`, `src/polysignal_lab/observability/safety.py`, safety scan evidence. | Complete. |
| SM-002 | Wallet secret usage = 0. | `Settings.validate_runtime_environment`, config-security tests, safety scan. | Complete. |
| SM-003 | Telegram signal success rate >= 99%. | `TelegramPublisher`, scheduler publish records, SQLite `telegram_publishes`, real Telegram send evidence path. | Path complete; live delivery depends on externally exported credentials. |
| SM-004 | Paper order creation rate >= 95%. | `PaperSimulator`, scheduler accepted-signal processing, SQLite/JSONL paper order logs. | Complete. |
| SM-005 | Stale paper fill = 0. | `OrderBook.is_fresh`, `BestAskTakerFillModel`, stale rejection tests/report metric. | Complete. |
| SM-006 | Paper result settlement rate >= 95%. | `PaperSettlementEngine`, scheduler settlement loop, paper result logs. | Complete. |
| SM-007 | Signal log completeness = 100%. | `JSONLStore`, `SQLiteStore.insert_signal`, scheduler `process_signal`. | Complete. |
| SM-008 | Paper result log completeness = 100%. | scheduler settlement logging, `JSONLStore`, `SQLiteStore.insert_paper_trade_result`. | Complete. |
| SM-009 | Duplicate signal rate < 2%. | `SignalDeduper`, `ConsensusEngine`, gate/dedupe tests, publish logs. | Complete. |
| SM-010 | Daily stats generation rate = 100%. | `PaperReportService`, scheduler `generate_daily_report`, SQLite `daily_reports`, Telegram daily report. | Complete. |

## Current Risk Register

| Risk | Evidence | Follow-up owner |
| --- | --- | --- |
| Live Gamma bounded page may not include configured crypto Up/Down markets. | Todo 18 evidence records a public fallback-market scheduler snapshot when needed. | Final QA should keep this explicit. |
| Final Telegram acceptance requires external credentials but `.env` must not be read. | Owner decision requires real channel send with externally supplied env vars and redacted evidence. | Final QA. |
