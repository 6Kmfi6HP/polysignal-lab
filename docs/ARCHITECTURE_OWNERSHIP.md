# Architecture Ownership

> Living document. Ownership and dependency direction after the native Nautilus migration.
>
> Companion: [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md)

## Three truths

| Truth | Owner | Must not own |
|---|---|---|
| **Nautilus Runtime** | `LiveNode`/`BacktestEngine`, DataEngine, ExecutionEngine, RiskEngine, Cache, Portfolio, native Order/Position, Account | Alpha formulas, market discovery rules, report sinks |
| **PolySignal Decision** | `MarketCatalog`, `MarketViewAssembler`, alpha cores, sole `DecisionPolicyActor`, pure `DecisionPolicy`, native order mapping, read-only Cache allocation rules | Live books, fill/order lifecycle, balances, exposure, portfolio ledger |
| **Reporting** | SQLite/JSONL, Telegram, dashboard projections, report-only settlement | Trading state mutation |

Any module that is not one of these three either becomes a collaborator of one truth or is quarantined/deleted.

## Dependency direction

```
Runtime mode dispatcher
  ├─ PolymarketDataClientFactory
  ├─ SandboxExecutionClientFactory or gated PolymarketExecutionClientFactory
  ├─ BacktestEngine with historical native data
  ├─ RTDS LiveDataClient (managed spot, single source)
  ├─ MarketRotationActor  (universe / metadata / PTB CustomData; no RTDS spot republish)
  ├─ DecisionPolicyActor  (sole owner; native Signal request/response)
  └─ PolySignalNativeStrategy + PolySignalStrategyConfig
        ├─ MarketViewAssembler  ← Cache-backed books + CustomData
        ├─ DecisionPipeline / NativeExitPolicy / native_order
        └─ observability hooks  → Reporting Truth
```

Rules:

1. Decision code does not import venue transports or legacy OrderBook/CLOB stacks.
2. Strategy remains a Nautilus callback host; multi-step business logic lives in collaborators under `nautilus_runtime/strategy/`.
3. Reporting consumes projections only; it never invents open positions or settlement fills.
4. Candidate/approval messages are frozen and serialized over native Signal.
5. Python 3.12 and the exact Nautilus dependency are required.

## Accepted boundaries (do not “fix”)

- `MarketCatalog` business-key boundary (condition/token → instrument id)
- `MarketViewAssembler` pure domain projection
- `Side` UP/DOWN vs Nautilus `OrderSide`
- `OrderIntent` vs `TimeInForce`
- `native_order` thin mapping (`order_factory` + `submit_order` only)
- `SignalGate` / consensus / arbitration as business policy (not RiskEngine)
- Settlement is **report-only** for sandbox/live under the verified latest package;
  backtest alone has a verified native contract-expiry matching-engine path
- RTDS spot via LiveDataClient only; SIDECAR vs RTDS client-id separation
- `NativeExitPolicy` over Cache positions (reduce-only in sandbox only);
  Polymarket live execution does not support reduce-only, and contingent/bracket
  orders remain disabled (`support_contingent_orders=False`)
- Report projections may record execution assumptions but cannot feed trading decisions.
- SQLite/JSONL runtime names are `report_orders`, `report_fills`,
  `report_positions`, `report_results`, and `report_account_snapshots`.
- Strategy custom state contains only research state or immutable intent; Cache
  orders, fills, positions, and tags reconstruct in-flight management.

## False-positive traps

High CBO/LCOM on Strategy/Actor/policy hubs is often framework-shaped or desirable fan-in. Metrics alone are not ownership failures.

## Locked version

Executable API truth: installed and locked
`nautilus_trader[polymarket]==1.231.0.dev20260716+16604`.
`docs/nautilus_reference/` is reference material, not a version lock.
The verified capability and migration-blocker details are recorded in
[`NAUTILUS_CAPABILITY_MATRIX.md`](NAUTILUS_CAPABILITY_MATRIX.md).

## Quality gates (native migration complete)

The migration is **complete for local / CI purposes** when all of the following hold.
It is **not** complete for live trading until separately authorized.

| Gate | Command / check | Pass criterion |
|---|---|---|
| Python tests | `NAUTILUS_REQUIRED=1 pytest` | All non-skipped tests pass |
| Pre-commit | `pre-commit run --all-files` | Hooks pass |
| Safety | `polysignal-safety-scan .` | Pass |
| Frontend | `npm run lint && npm run build && npm test` (in `frontend/`) | Pass |
| Typecheck | `basedpyright` | **0 new errors** vs `.basedpyright/baseline.json` |
| Live default | config / composition | `execution_mode` default sandbox; live factory unregistered without all gates |

### Typecheck policy

- Full-repo **zero errors** is intentionally **not** the completion bar while
  Nautilus pyo3 stubs and test fakes produce large baseline noise.
- `.basedpyright/baseline.json` freezes known diagnostics. CI fails only on
  **new** unbaselined errors.
- Reduce debt by fixing real issues (baseline shrinks automatically) or, rarely,
  `basedpyright --writebaseline` when intentionally accepting new debt — never
  as a routine workaround.
- Capability tests that `pytest.skip` for missing public Nautilus inject /
  reconnect APIs are **boundary evidence**, not open defects.

### Out of scope until authorized

- Real Polymarket private account connectivity
- Live data/execution E2E, real orders, funds, redeem/payout
- Authenticated reconciliation reconnect/restart
- Production SQLite user-database migration
