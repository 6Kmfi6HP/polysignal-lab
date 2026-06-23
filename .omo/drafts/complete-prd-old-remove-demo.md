---
slug: complete-prd-old-remove-demo
status: approved-for-plan
intent: clear
pending-action: run post-approval Metis review, then write .omo/plans/complete-prd-old-remove-demo.md
approach: phased HEAVY remediation plan: replace demo-backed fixtures with test-only factories, remove demo runtime/docs/artifacts from product surfaces, align product scope strictly to PRD-old final scope, repair live read-only market-data orchestration, align the three PRD strategies and paper lifecycle, then prove with unit/integration/real-surface QA and subagent review.
---

# Draft: complete-prd-old-remove-demo

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->

| id | outcome | status | evidence path |
| --- | --- | --- | --- |
| C1 | Product/runtime scope exactly follows docs/PRD-old.md, with demo and non-PRD strategy surfaces removed or isolated | active | docs/PRD-old.md; pyproject.toml; docker-entrypoint.sh; config/signal_bot.yaml; src/polysignal_lab/app/demo.py; src/polysignal_lab/strategies/skew_mean_reversion.py |
| C2 | Real read-only market data pipeline discovers crypto Up/Down markets, subscribes CLOB market WS after token discovery, ingests Binance spot, and builds fresh snapshots | active | src/polysignal_lab/app/scheduler.py:136-288; src/polysignal_lab/data/*; Polymarket docs market data/WebSocket; Binance Spot WS docs |
| C3 | Three PRD strategies match PRD-old trigger semantics and produce auditable SignalCandidate metrics/reasons | active | docs/PRD-old.md §10; src/polysignal_lab/strategies/*.py; src/polysignal_lab/config.py:193-295 |
| C4 | Telegram + paper simulation + settlement + report lifecycle works without real trading, including WIN/LOSS/VOID/UNKNOWN and configured paper TP/SL behavior | active | docs/PRD-old.md §12-14, §20-23; src/polysignal_lab/publish; src/polysignal_lab/paper; src/polysignal_lab/signal_layer |
| C5 | Persistence, dashboard, CLI/Docker, and safety gates are tested through real surfaces and no longer depend on demo code | active | src/polysignal_lab/storage; src/polysignal_lab/dashboard/app.py; src/polysignal_lab/app/main.py; Dockerfile; tests/*; scripts/safety_scan.py |
| C6 | Research and implementation documentation is current, cited, and does not preserve stale demo claims | active | docs/*.md; official Polymarket/Binance/Telegram/FastAPI docs; README.md |
| C7 | Subagent workflow owns parallel research/implementation/review lanes with non-overlapping write scopes and final main-thread integration | active | user request; multi_agent lanes 019eec72-* |

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->

| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| Source of truth | docs/PRD-old.md overrides docs/PRD.md, README, and current implementation summaries | User explicitly named PRD-old | yes |
| Scope interpretation | Implement final PRD-old product including §25 MVP and §26 second-version items already named there, but remove features not named in PRD-old | Owner approved full scope: "范围是全部" | no |
| Safety boundary | Never add authenticated Polymarket client, private key/API key handling, order creation/cancel/submit, redeem, transfer, or CEX orders | PRD-old §§4.2, 7.2, 22, 23.2 prohibit these paths | no, unless user changes product goal |
| Telegram QA | Plan must include a real Telegram channel send as a required acceptance scenario, using externally supplied env vars and redacted evidence | Owner approved: "发送频道必须真实"; PRD needs channel publishing; secrets must still not be committed or read from .env | no |
| External API tests | Use mocked/local protocol tests for deterministic CI, plus bounded read-only live smoke commands for Gamma/CLOB/Binance where safe | Live markets are unstable; PRD needs real data path confidence | yes |
| Demo removal | Product runtime commands/docs must remove demo; synthetic builders may remain only under tests as test factories, not under src/polysignal_lab/app | Tests need deterministic data after demo removal | yes |
| Historical artifacts | Delete generated historical run artifacts such as logs/state/runtime SQLite/scan outputs during execution, after confirming paths are generated artifacts and not source assets | Owner approved: "历史删除" | no |
| .env handling | Do not read, modify, delete, or include .env in plan evidence | Security boundary and likely secret content; owner approval covers generated history, not secrets | no |
| Subagents | Use subagents for read-only research, module implementation workers with disjoint write sets during execution, and final reviewers; main worker integrates | User required subagents; reduces merge risk | yes |

## Findings (cited - path:lines)

- PRD-old defines the product as a read-only Polymarket short-cycle signal + paper simulation system: Market Data -> Strategy Signal -> Signal Gate -> Telegram -> Paper Simulation -> Win/Loss Report. See docs/PRD-old.md §§1-4, §§8-9.
- PRD-old final scope includes the three named strategies only: VWAP Momentum, Late Consensus, PTB Diff. See docs/PRD-old.md §10 and §§25-26.
- PRD-old safety boundary prohibits private keys, authenticated order clients, create/cancel/submit order, EIP-712 signing, redeem, transfer, CEX live orders, and real sell execution. See docs/PRD-old.md §§4.2, 7.2, 22, 23.2.
- Current config/runtime includes extra non-PRD assets and strategy: DOGE/BNB/HYPE and `skew_mean_reversion` are enabled in config/signal_bot.yaml and built by src/polysignal_lab/strategies/factory.py. Explorer evidence: src/polysignal_lab/config.py:297-315, config/signal_bot.yaml:133-169.
- Demo code is product-path contamination: src/polysignal_lab/app/demo.py randomizes fake market state and randomized WIN/LOSS settlement; src/polysignal_lab/app/demo_data.py provides fake markets/books/spots; pyproject.toml exposes `polysignal-demo`; docker-entrypoint.sh exposes `demo`. CodeGraph evidence: src/polysignal_lab/app/demo.py:30-230 and src/polysignal_lab/app/demo_data.py:12-49.
- Current tests depend on demo fixtures: tests/conftest.py imports sample_market/sample_book/sample_spot from src/polysignal_lab/app/demo_data.py; tests/test_demo_e2e.py imports run_demo. This will break when demo is removed unless test-only factories are created first.
- Current scheduler starts WebSockets before the first market discovery. If `ctx.markets` is empty, `start_websockets()` logs fallback and never subscribes Polymarket market WS. Evidence: src/polysignal_lab/app/scheduler.py:254-288 and run loop calls start_websockets before refresh at src/polysignal_lab/app/scheduler.py:587-604.
- Current Polymarket market discovery is slug-pattern based for crypto up/down markets; it may miss active markets if slug shape changes. Evidence: src/polysignal_lab/data/polymarket_market_discovery.py:71-81.
- Current Polymarket WS handler reads `payload.get("changes", [])` for `price_change`, while official Polymarket WSS market docs show `price_changes`. Evidence: src/polysignal_lab/data/polymarket_clob_ws.py:62-80 and https://docs.polymarket.com/api-reference/wss/market.
- Current `Market.from_gamma()` parses active/closed/resolved status and `price_to_beat`, but does not populate `resolved_outcome`; `PaperSettlementEngine.settle()` requires `market.resolved_outcome` to classify WIN/LOSS. Evidence: src/polysignal_lab/domain/market.py:48-107 and src/polysignal_lab/paper/settlement.py:15-25.
- Current VWAP Momentum implements VWAP/deviation/momentum/favorite/time window but does not implement PRD-old `z_score` config/trigger as a gate. Evidence: src/polysignal_lab/strategies/vwap_momentum.py:197-260 and src/polysignal_lab/config.py:193-210.
- Current Late Consensus uses ask_sum and confidence_abs but does not explicitly gate on snapshot.max_spread or Binance asset spot movement as PRD-old input/rule language requires. Evidence: src/polysignal_lab/strategies/late_consensus.py:40-175 and docs/PRD-old.md §10.2.
- Current PTB Diff uses C1-C4 `min_prob/max_prob` rather than PRD-old trigger rows with `max_token_price` and `min_probability_edge`. Evidence: src/polysignal_lab/strategies/ptb_diff.py:89-169 and docs/PRD-old.md §10.3, §17.
- Current pytest is red: `.venv/bin/python -m pytest -q` reports 34 tests with 18 failures. Root cause is strategy fixture mismatch: PTB default `min_prob=0.80` rejects fixture UP ask 0.62; Late Consensus requires confidence_abs 0.30 but fixture skew is 0.24; dependent gate/paper/storage tests crash on empty signals.
- Safety scan passes for product source: `.venv/bin/python scripts/safety_scan.py src` -> Safety scan passed. `scripts/safety_scan.py .` fails because it scans `.venv` and flags third-party `cancel_all`, so plan must fix scan exclusions or standard command scope.
- Polymarket official docs: market data REST is public, no auth/wallet needed; Gamma exposes `/events` and `/markets`; CLOB read endpoints include `/book`, `/prices`, `/midpoint`, `/spread`; authenticated CLOB order endpoints require private-key/API auth. Sources: https://docs.polymarket.com/market-data/overview, https://docs.polymarket.com/api-reference/authentication.
- Polymarket official market WebSocket is public and uses `/ws/market`; subscription request includes `assets_ids` and `type: market`; events include `book`, `price_change`, `last_trade_price`, `best_bid_ask`, and market lifecycle updates. Source: https://docs.polymarket.com/api-reference/wss/market.
- Polymarket official fetching-markets guide recommends `events?active=true&closed=false` with pagination for broad active discovery. Source: https://docs.polymarket.com/market-data/fetching-markets.
- Binance official Spot WS docs state `<symbol>@bookTicker` pushes real-time best bid/ask updates and payload includes symbol, bid, ask, and quantities. Source: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams.
- Telegram Bot API `sendMessage` sends text messages and requires `chat_id` plus 1-4096 char `text`; `parse_mode` is optional. Source: https://core.telegram.org/bots/api.
- Live read-only smoke: `curl 'https://gamma-api.polymarket.com/events?active=true&closed=false&limit=3'` returned active events; `curl -i 'https://clob.polymarket.com/book?token_id=invalid-token-for-planning'` returned HTTP 404 JSON error without auth, confirming endpoint reachability.

## Decisions (with rationale)

- Plan as CLEAR intent: the target outcome is explicit (complete PRD-old, remove demo), but destructive cleanup and phase/scope interpretation require owner confirmation before final plan.
- Treat this as HEAVY: changes span external integrations, scheduler concurrency, config/schema, storage, tests, docs, Docker, security, and deletion.
- Make implementation TDD/characterization-first: every behavior change starts with a failing test or current red test captured; refactors/removals get characterization tests before code movement.
- Replace demo fixtures before deleting demo runtime: first move synthetic factories into `tests/factories.py` or equivalent, then update tests, then delete `src/polysignal_lab/app/demo.py`, `src/polysignal_lab/app/demo_data.py`, `polysignal-demo`, `demo` Docker entrypoint branch, and demo docs.
- Keep dashboard/SQLite/consensus/daily reports/leaderboard because PRD-old §26 names them as second-version scope and owner approved full scope.
- Remove or disable `skew_mean_reversion` and DOGE/BNB/HYPE by default because they are not in PRD-old named scope.
- Keep Telegram `dry_run: true` as local default only for safe development/tests, but require an explicit real-channel send QA path before final acceptance. Evidence must redact token/chat identifiers.
- Delete generated historical artifacts during execution: `logs/`, `state/`, runtime `data/*.sqlite*`, `scan_results.json`, `refined_results.json`, caches, and similar generated outputs after verifying they are not source assets. Do not read, modify, or delete `.env`.
- Create implementation documentation, not only code changes: external API research notes and final PRD-old compliance/reporting documentation are part of done.
- Use official docs as primary source for external API assumptions; no Medium/third-party claims are authoritative.

## Scope IN

- Align runtime product scope to docs/PRD-old.md final scope (§25 + §26 + §28).
- Remove demo runtime, CLI, Docker, docs, and app-package fake data.
- Move deterministic synthetic data needed by tests into test-only factories.
- Repair market discovery/orderbook/ws/spot/snapshot lifecycle and subscription order.
- Align VWAP Momentum, Late Consensus, and PTB Diff config/schema/logic/metrics/reasons to PRD-old.
- Repair signal gate, dedupe, Telegram formatting/publisher logging, paper simulator, settlement, report generation, and storage paths as needed to satisfy AC/SIM/SEC.
- Add/repair tests and real-surface QA for CLI scheduler, dashboard endpoints, safety scan, bounded read-only live market data smoke, Docker modes if available, and Telegram dry-run.
- Update README/docs/implementation docs with current PRD-old compliance and cited external research.
- Use subagents during execution for module workers and reviewers with explicit file ownership.

## Scope OUT (Must NOT have)

- No authenticated Polymarket CLOB client.
- No private key, mnemonic, seed phrase, POLY secret, wallet secret, trading secret, API key generation, or `.env` inspection.
- No real order creation, cancellation, submission, signed order, sell, redeem, transfer, CEX order, or chain transaction.
- No historical replay/backtest beyond live paper simulation unless required only as deterministic tests.
- No paid channel/subscription/payment work.
- No deletion outside the owner-approved generated-history manifest; `.env` is never read, modified, or deleted.
- No demo command, demo app module, randomized fake product runtime, or product docs claiming demo as acceptance after cleanup.
- No extra non-PRD strategies/assets in default runtime.

## Open questions

All owner forks are answered:

1. Scope phase: full PRD-old final scope (§25 + §26 + §28), not first-version-only.
2. Demo/data deletion: delete generated historical artifacts; do not read, modify, or delete `.env`.
3. Research documentation: create documentation.
4. Telegram acceptance: real Telegram channel send is required.

## Post-approval Metis review

verdict: OKAY_TO_WRITE_PLAN

Integrated required additions:

- Paper TP/SL/max-hold exits must be wired into scheduler/runtime, not left as an unused engine.
- PRD-facing result states must be WIN/LOSS/VOID/UNKNOWN; existing SPLIT behavior must be removed or strictly isolated from acceptance.
- Telegram token/channel validation must happen at startup when publishing is enabled, not only at send time.
- Full final scope must explicitly prove consensus, SQLite, daily report, dashboard, and strategy leaderboard.
- Generated-history deletion must use an exact manifest: `logs/`, `state/`, `data/paper_trades.sqlite`, `data/polysignal_lab.sqlite3`, `scan_results.json`, `refined_results.json`, caches/equivalent generated outputs.
- Real Telegram send must run after formatter, publisher logging, redaction, safety, and docs are stable.

## Approval gate
status: approved
pending action: run post-approval Metis review, then write detailed todos into .omo/plans/complete-prd-old-remove-demo.md
brief: Plan will target strict PRD-old final scope, remove demo runtime surfaces, keep only test-only synthetic factories, delete generated historical artifacts while preserving secrets, remove non-PRD default strategy/assets, repair scheduler/data contracts/strategy semantics/settlement, create research/compliance docs, and require TDD plus real-surface QA including a real Telegram channel send.
<!-- When exploration is exhausted and unknowns are answered, record the approval gate status here. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
