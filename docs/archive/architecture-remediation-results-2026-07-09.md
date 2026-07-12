# NautilusTrader Architecture Remediation Results

## Scope

Remediation plan `docs/superpowers/plans/2026-07-09-nautilus-architecture-remediation.md` (Tasks 1–14) executed in isolated worktree `.worktrees/nautilus-architecture-remediation` on branch `refactor/nautilus-architecture-remediation`.

Goals addressed: deterministic CustomData replay, shared decision-policy ownership, actor-safe market discovery, dead-code removal, duplication consolidation, alpha module extraction, and lint cleanup — without changing default Python 3.11 Nautilus independence or SANDBOX execution.

## Commits

Base: `0076538`

| Commit | Subject |
|--------|---------|
| `f02a658` | fix: derive custom data freshness from event time |
| `0291b2f` | fix: reject globally stale cross-market views |
| `7b5429f` | fix: remove stale market catalog token indexes |
| `0d10e4b` | refactor: require shared decision policy injection |
| `fd67058` | refactor: require complete Nautilus runtime class set |
| `597bf2f` | refactor: move market discovery off actor callbacks |
| `02e277b` | refactor: unify cross-market decision submission |
| `c86b9f5` | refactor: remove obsolete runtime compatibility code |
| `fd43a0d` | refactor: centralize optional Nautilus imports |
| `b762b27` | refactor: consolidate repeated discovery and persistence paths |
| `5409203` | refactor: move legacy snapshot adapters out of PTB core |
| `a7a32a2` | refactor: separate VWAP history and state codecs |
| `8779ac0` | chore: remove stale imports and local variables |

Documentation and verification fixes land in the Task 14 commit on top of `8779ac0`.

## Verification Commands

```bash
# Static analysis (2026-07-10)
uvx pyscn@latest analyze --select communities --json src/polysignal_lab
uvx pyscn@latest analyze --select deps,cbo,lcom --json src/polysignal_lab
uvx pyscn@latest analyze --select complexity,deadcode,clones --min-complexity 5 --min-severity info --clone-threshold 0.65 --json src/polysignal_lab tests
uvx vulture@latest src/polysignal_lab --min-confidence 80 --sort-by-size
uv run ruff check src/polysignal_lab --select F401,F841

# Core Nautilus regression set
uv run pytest tests/test_nautilus_custom_data.py tests/test_nautilus_market_view_assembler.py \
  tests/test_nautilus_cross_market.py tests/test_nautilus_market_catalog.py \
  tests/test_nautilus_market_rotation.py tests/test_nautilus_decision_policy.py \
  tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py \
  tests/test_nautilus_full_paper_runtime_smoke.py tests/test_nautilus_dependency_boundary.py \
  tests/test_nautilus_observability.py tests/test_storage_restore.py \
  tests/test_storage_reporting_publish.py -q

# Full suite + safety scan
uv run pytest -q
uv run polysignal-safety-scan .

# Bridge validation (Python 3.12 + Nautilus extras)
uv run --python 3.12 pytest tests/test_nautilus_full_paper_runtime_smoke.py \
  tests/test_nautilus_cache_market_data.py tests/test_nautilus_dependency_boundary.py -v
```

## Before/After Metrics

| Metric | Before (2026-07-09 review) | After (2026-07-10) | Gate |
|--------|------------------------------|--------------------|------|
| pyscn health score | 76/100 (B) | 86/100 (B) deps; 84/100 (B) complexity | — |
| Dependency cycles | 0 | 0 | ≤ baseline |
| High-coupling classes (CBO ≥ 8) | 26 / 225 (8 flagged in plan) | 7 / 137 | ≤ 8 ✅ |
| Clone groups | 40 (plan baseline) | 35 | < 40 ✅ |
| Cloned fragment % | 13.2% (plan baseline) | 11.8% | < 13.2% ✅ |
| High-risk complexity functions | 9 (plan baseline) | 9 | ≤ 9 ✅ |
| `PolySignalNativeStrategy` lines | 724 | 513 | reduced |
| `PolySignalNativeStrategy` CBO | 25 | 11 | reduced |
| `PolySignalNativeStrategy` LCOM4 | 5 (legacy metric) | 31 | still high-cohesion risk |
| `vwap_momentum_core.py` lines | 689 | 556 | reduced via extraction |
| Vulture 80% findings | — | 0 lines output | clean ✅ |
| Ruff F401/F841 | 36 issues | 0 | 0 ✅ |
| pytest | 722 passed (setup baseline) | 751 passed | all pass ✅ |

## Fixed Findings

- CustomData `PriceToBeatView.updated_at` derives from `ts_event`, not wall clock.
- Cross-market group views reject globally stale and skewed members.
- Market catalog token indexes stay consistent on replacement.
- Shared `DecisionPolicy` injected at assembly; strategies no longer create private policies.
- Runtime class triple is complete and static; incomplete sets fail closed.
- Market discovery runs in `MarketDiscoveryWorker`; actor timers only enqueue/apply results.
- Cross-market uses the shared native decision pipeline; standalone `cross_market_bot.py` removed.
- Dead compatibility modules removed (`projection_recorder`, unused decision-pipeline helpers, legacy persistence hooks).
- Optional Nautilus imports centralized in `optional_imports.py`.
- Discovery and SQLite payload helpers deduplicated.
- Legacy snapshot adapters moved to `alpha/legacy_snapshot_adapter.py`.
- VWAP trade history and state codec extracted to `vwap_trade_history.py` / `vwap_state.py`.
- Ruff F401/F841 cleaned across `src/polysignal_lab`.

## Accepted Boundaries

- **Optional Nautilus imports** (`optional_imports.py`, `live_node.py` lazy loader): intentional so Python 3.11 default install stays Nautilus-free. Not a defect; static imports only inside the optional extra path.
- **`OrderBookRegistry` / domain `OrderBook`**: legacy compatibility and read-only projection path. Nautilus `Cache` remains execution truth in the Nautilus runtime.
- **Custom SQLite observability store**: application projection backend; not replaced by Nautilus `Database` in this remediation.
- **`TelegramBotService`, `SignalGate`, dashboard calibration helpers**: high complexity accepted; out of scope for this plan.
- **Default execution**: `Environment.SANDBOX` with Polymarket data client only — verified by smoke tests.

## Remaining Debt

- `PolySignalNativeStrategy` still 513 lines with LCOM4=31 — further decomposition deferred.
- `TelegramBotService` (CBO=11) and `MarketRotationActor` (CBO=10) remain high-coupling hotspots.
- Custom `domain/orderbook.py` vs Nautilus `L2OrderBook` — not migrated.
- Standalone Polymarket HTTP/WS clients outside Nautilus adapter pattern.
- Empty `src/polysignal_lab/strategies/` directory stub (if still present).
- `scheduler` alias documentation in folder indexes may still reference legacy paths.

## Test Results

| Suite | Result |
|-------|--------|
| Task-focused regressions (per task) | PASS |
| Core Nautilus collection (Task 14 Step 2) | PASS |
| Full `uv run pytest -q` | **751 passed**, 0 failed, 0 skipped |
| `uv run polysignal-safety-scan .` | PASS |
| Python 3.12 bridge smoke (`full_paper_runtime_smoke`, `cache_market_data`, `dependency_boundary`) | 12 passed |

Warnings (pre-existing, non-failing): Nautilus parquet `Timedelta` deprecation (×2), Starlette `httpx` deprecation in FastAPI test client.

## Known Environment Limitations

- Nautilus integration tests require Python 3.12+ with `[nautilus]` optional dependencies installed in the worktree venv.
- pyscn `--json` stdout may be empty; reports are written under `.pyscn/reports/analyze_*.json`.
- Static native-strategy unit test uses stub `nautilus_trader` submodules; updated to include `policy` injection and model/core stubs required by current import graph.
