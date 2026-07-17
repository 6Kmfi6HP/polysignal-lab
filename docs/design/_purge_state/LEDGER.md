# Purge Ledger

| Round | Batch | Path | Tag | Action | Reason | Tests |
|-------|-------|------|-----|--------|--------|-------|
| 1 | B1 | `src/**/__pycache__`, `tests/**/__pycache__` | LEGACY_DUAL | delete | Stale bytecode for deleted modules (clob/paper/actor/…) | skipped |
| 1 | B3 | `src/polysignal_lab/domain/orderbook.py` | NT_DUP_RUNTIME / LEGACY_DUAL | delete | Domain Pydantic book duplicated Cache/`SideBookView` projection; zero runtime consumers | factories + telegram tests retargeted to SideBookView |
| 1 | B1 | `src/polysignal_lab/nautilus_runtime/strategies/` | LEGACY_DUAL | delete | Empty re-export stub | test_nautilus_strategy_wrappers fixed |
| 1 | B1 | `tests/test_scheduler_paper.py` | LEGACY_DUAL | delete | Stub for removed scheduler path | n/a |
| 1 | B1 | FOLDER_INDEX / PROJECT_INDEX ghosts | DOC_DRIFT | rewrite | Ghost files and wrong tree | regenerated |
| 1 | — | `Side`/`OrderIntent`/`MarketCatalog`/alpha/`SignalGate`/`native_order`/… | KEEP_DOMAIN | keep | Accepted NT boundaries / product domain | — |
| 2 | B4 | `native_strategy.py` multi-step methods | GOD_OBJECT | move | Thin NT host; logic in strategy/* | strategy/platform/safety/native_exit green |
| 2 | B4 | `strategy/{readiness,market_data_events,condition_evaluation,config_deps,lifecycle}.py` | GOD_OBJECT | create | Collaborators for thin Strategy | covered via strategy tests |
| 2 | AUDIT | CLOB/OrderBookRegistry/Paper* in `src/` | LEGACY_DUAL | keep (forbid only) | Present only in safety.py forbid list | safety-scan PASS |
| 2 | AUDIT | `sqlite_store.py` clone mass | CLONE / REPORT_ONLY | defer B6 | Report CRUD clones | — |
| 2 | AUDIT | alpha `*_core` decision/hedge clones | CLONE | defer B7 | Type-1/2 clones across cores | — |
| 3 | B5 | `strategy/helpers.py` `_identity_instrument_id` | NT_DUP_ADAPTER | delete | Defaulted instrument_id=token_id; dual vs NT `get_polymarket_instrument_id` | strategy/native_order green |
| 3 | B5 | `strategy/helpers.py` `catalog_instrument_id_resolver` | NT_DUP_ADAPTER | create | Single catalog→NT id resolve path | used by Strategy + config_deps |
| 3 | B5 | `native_strategy.py` default identity resolver | NT_DUP_ADAPTER | delete | Default now catalog_instrument_id_resolver(registry) | strategy green |
| 3 | B5 | `polymarket_adapter.py` `to_nautilus_order_status` | LEGACY_DUAL | delete | Zero production callers; NT events already carry OrderStatus | enum_parser + contracts updated |
| 3 | B5 | `L1_RAW_DELTA_FALLBACK_PHASE` exports | LEGACY_DUAL | delete | Dead dual-path book-phase marker (no runtime use) | strategy tests still assert phase string absent |
| 3 | B5 | `domain/market.py` soft-fail around `parse_polymarket_instrument` | NT_DUP_ADAPTER | delete | Silent dual path; now hard-requires NT parser for outcome labels | market_parsing + universe fixtures NT-legal ids |
| 3 | B5 | `market_catalog.py` `_nautilus_polymarket_instrument_id` | NT_DUP_ADAPTER | create | Single official helper call site for default id resolve | market_catalog tests |
| 3 | B5 | `PolymarketEnumParser` side/TIF maps | KEEP_DOMAIN | keep | Domain Side/OrderIntent → NT order enums; not NT-provided | native_order |
| 3 | B5 | Gamma field enrichment (ptb/status/resolution) | KEEP_DOMAIN | keep | NT BinaryOption has no crypto PTB / UMA resolution domain | market_parsing |
| 3 | AUDIT | pyscn clones ~10%, 0 cycles, health C | CLONE | defer | Mass in sqlite_store + alpha; not runtime dual | B6/B7 |
| 4 | B6 | `sqlite_store.query_daily_reports` | CLONE / dual API | delete | Dual of `daily_reports` (ReportingReadPort name is canonical) | storage + reporting tests |
| 4 | B6 | `sqlite_store.query_strategy_leaderboard` | CLONE / dual API | delete | Dual of `strategy_leaderboard` | storage restore tests |
| 4 | B6 | `delete_report_result_rows` / `delete_daily_report_rows` bodies | CLONE | move | Shared `_delete_row_and_optional_publish` | persistence tests |
| 4 | B6 | `PersistenceService.query_daily_reports` | KEEP_DOMAIN | keep | Telegram/facade name; wraps store.daily_reports | telegram tests |
| 4 | B6 | SQLiteStore publish-outbox / migrate mass | REPORT_ONLY / GOD_OBJECT | defer | All methods referenced; split needs dedicated outbox extraction | — |
| 4 | AUDIT | paper_* migration in projection_migration | REPORT_ONLY | keep | One-shot legacy DB upgrade; drops paper tables | projection_migration tests |
| 5 | B7 | `dump_hedge_core._decision` | CLONE | delete | Pure wrapper of `build_order_decision` | alpha dump_hedge tests |
| 5 | B7 | `low_side_dual_reversion_core._decision` | CLONE | delete | Pure wrapper of `build_order_decision` | (covered via wrappers/strategy) |
| 5 | B7 | `pre_order_market_core._decision` | CLONE | delete | Pure wrapper of `build_order_decision` | alpha pre_order tests |
| 5 | B7 | `cross_market_core._decision` | CLONE | delete | Pure wrapper of `build_order_decision` | alpha cross_market tests |
| 5 | AUDIT | dump vs dual hedge-stop bodies | CLONE | keep | Shared via `build_hedge_order_decision`; params differ | — |
| 5 | AUDIT | `projections.project_*` vs `strategy/event_projection.project_*` | KEEP | keep | Dict telemetry vs Alpha*Event; different consumers | — |
| 5 | AUDIT | pyscn clone 9.6%, 0 cycles, health 87 B | CLONE | continue | Residual store insert clones + hedge bodies | B8/B9 |
| 6 | B8 | `safety.py` LEGACY_* forbid expansion | LEGACY_DUAL | update | Block reintro of DecisionPolicyActor, nautilus_bridge, MatchingEngine(, PaperFill*, domain.paper_*, shadow_wallet | safety + platform static gates |
| 6 | B8 | `safety._legacy_dual_path_imports` bridge/paper/actor AST | LEGACY_DUAL | update | Import-level dual-path detection beyond string scan | test_safety new case |
| 6 | B8 | `native_strategy._call_core` / `_order_event` / `_fill_event` / `_should_notify_fill` / `_forget_approved_metrics` | GOD_OBJECT | delete | Zero callers; order_events owns these | strategy/native_exit green |
| 6 | B8 | `native_strategy._record_observability` | GOD_OBJECT | delete | Zero callers; sink uses specific record_* | strategy green |
| 6 | B8 | `native_strategy._retry_market_instrument_requests` / `_condition_instruments` / `_clear_condition_subscription_state` / `_unsubscribe_market_instrument` | GOD_OBJECT | delete | Zero callers; subs helpers used via manager/other hosts | strategy green |
| 6 | AUDIT | runtime dual path (CLOB/registry/paper) in src | LEGACY_DUAL | keep (forbid only) | Already deleted; only safety strings remain | safety-scan PASS |
| 6 | AUDIT | order path sole native_order | KEEP | keep | Only `order_factory`+`submit_order` via native_order | native_order tests |
| 6 | AUDIT | SQLiteStore ~2k LOC | GOD_OBJECT / REPORT_ONLY | defer B9 residual | Report CRUD clones not trading dual | — |
| 6 | AUDIT | Strategy 431 > 400 STOP target | GOD_OBJECT residual | continue | Required Protocol/on_* surface; further needs Protocol redesign | B9 |
| 6 | AUDIT | pyscn full: 0 cycles, clone 9.6%, health 74 C | CLONE | accept residual | Store/report clones dominate; not NT dual | B9 |
| 7 | B9 | dual symbols in `src/` outside `safety.py` | LEGACY_DUAL | keep (absent) | OrderBookRegistry/CLOB/Paper*/DecisionPolicyActor/bridge = 0 hits outside safety forbid | safety-scan PASS |
| 7 | B9 | `runtime_registration` | KEEP | keep | Only `MarketRotationActor` + `PolySignalNativeStrategy` Importable registration | node/platform tests |
| 7 | B9 | order submit sites | KEEP | keep | Sole production submit: `native_order` → `order_factory.limit` + `submit_order` | native_order/pipeline |
| 7 | B9 | `native_strategy.py` LOC | GOD_OBJECT residual | keep | **342 ≤ 400**; host is DI + on_* only | strategy tests |
| 7 | B9 | deleted modules | LEGACY_DUAL | confirm absent | no `decision_policy_actor` / `decision_messages` / `nautilus_bridge` / `paper` package | existence checks |
| 7 | B9 | zombie pyc | LEGACY_DUAL | confirm 0 | no pyc without corresponding py under src | find scan |
| 7 | B9 | FOLDER_INDEX ghosts (runtime) | DOC_DRIFT | confirm 0 | all mentioned .py exist | index scan |
| 7 | B9 | SQLiteStore ~2079 LOC | REPORT_ONLY / GOD_OBJECT | keep | Report projection only; not trading truth | storage tests |
| 7 | B9 | pyscn deps/clones/cbo | CLONE | accept residual | 0 cycles; clone 9.5%; health 84 B; high CBO 3 | analyze_20260717_232250 |
| 7 | B9 | quality gates | — | pass | safety-scan + platform/safety/dependency + full `NAUTILUS_REQUIRED=1 pytest` green | B9 VERIFY |
| 7 | B9 | `strategy/host_init.py` | GOD_OBJECT | create | DI + instrument cache resolve extracted from Strategy host | platform/strategy green |
| 7 | B9 | `native_strategy.py` __init__/pipeline bind | GOD_OBJECT | move | Thin host; LOC 431→342 (≤400) | full pytest green |
| 7 | B9 | `tests/fixtures/public_market_payloads.json` token ids | LEGACY_DUAL / B5 residue | rewrite | `token-up/down` → numeric NT-legal `111/222` for parse_polymarket_instrument | integration smoke green |
| 7 | B9 | `test_integration_smoke` clob token set | LEGACY_DUAL | update | Match NT-legal fixture tokens | integration smoke |
| 7 | B9 | `test_strategy_owns_decision_policy` | DOC_DRIFT | update | Policy assignment lives in host_init | platform boundary |
| 7 | AUDIT | runtime dual path in src | LEGACY_DUAL | keep (forbid only) | Only safety.py forbid strings | safety-scan PASS |
| 7 | AUDIT | order path sole native_order | KEEP | keep | only order_factory+submit_order | native_order tests |
| 7 | AUDIT | SQLiteStore ~2k / clone 9.6% | REPORT_ONLY | accept | Not trading dual; optional later | STOP |
| 7 | AUDIT | runtime_registration Actors | KEEP | keep | MarketRotationActor + PolySignalNativeStrategy only | registration tests |
| 8 | B10 | `signal_layer/deduper.py`, `rate_limit.py` | LEGACY_DUAL | confirm absent | Already deleted pre-Round-8; zero production imports | n/a |
| 8 | B10 | `signal_layer/gate.py` `_commit_rejections` | LEGACY_DUAL / F01 | delete | Zero callers; dormant rejection batch helper | test_signal_gate |
| 8 | B10 | `live_node.py` credential validators + env inject | NT_DUP_ADAPTER / F02 | delete | Stop Python secret read/inject; Rust adapter resolves; keep allow_live_* gates only | trading_node/node tests rewritten |
| 8 | B10 | `node.py` pre-context credential validate call | NT_DUP_ADAPTER / F02 | delete | Dual gate with deleted validators | node prepare test retargeted |
| 8 | B10 | `subscriptions.wire_condition_ids` | SHADOW_TRUTH / F03 | delete→intent | Renamed `subscribe_intent_condition_ids`; never claim wire confirm; readiness `subscribe_requested` | strategy_base |
| 8 | B10 | `readiness.wire_subscribed` / `"subscribed"` | SHADOW_TRUTH / F03 | delete | Removed confirmed-wire status string | strategy/readiness |
| 8 | B10 | `custom_data_types.CythonCustomData` branch | LEGACY_DUAL / F04 | delete | `unwrap_custom_data` accepts only `nautilus_pyo3.CustomData` | custom_data tests |
| 8 | B10 | `native_strategy` `on_quote`/`on_book`/`on_trade`/`on_book_deltas` | LEGACY_DUAL / F05 | delete | Keep only on_*_tick / on_order_book / on_order_book_deltas | strategy tests |
| 8 | B10 | `helpers._fallback_fill_price` + Side.UP default | FABRICATION / F06 | delete | Unresolved side / missing positive fill price raises; order_events quarantine | strategy/event_projection |
| 8 | B10 | `projections.project_nautilus_*` SimpleNamespace | MIDDLE_LAYER / F07 | delete | Single dict path via `project_order_event`/`project_fill_event` + metrics kwarg | issue15 + hooks |
| 8 | B10 | `storage._ORDER_STATUSES` DENIED→REJECTED etc. | SHADOW_TRUTH / F07 | rewrite | Preserve native statuses; unknown → empty (invalid for dashboard) | projection_migration/dashboard |
| 8 | B10 | duplicate `event_datetime` in helpers | CLONE / F08 | consolidate | Sole strict primitive in `custom_data_state.event_datetime`; helpers re-exports | market_data/event_projection |
| 8 | B10 | `market_discovery_worker.close` wait=False | DETACHED / F09 | rewrite | `shutdown(wait=True)`; delete post-close continue-refresh test | market_rotation |
| 8 | B10 | `cross_market_core.evaluate` + `_evaluate_relation` | DEAD_PATH / F10 | delete | Fabricated missing legs removed; evaluate() returns []; evaluate_group only | cross_market tests |
| 8 | B10 | `domain/market.py` index UP/DOWN + ACTIVE default | FABRICATION / F11 | delete | Require outcome labels; unknown status stays UNKNOWN; active default False | market_parsing |
| 8 | B10 | early-exit notify durable claim comment | OBS_CLAIM / F12 | rewrite | Clarify settlement FATAL_ON_LOSS vs best-effort notify | order_events |
| 8 | B10 | storage normalize up_ask/down_ask price scrape | FABRICATION / F06 | delete | Report price from row/level_price only | issue15 |
