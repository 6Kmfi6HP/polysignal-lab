# Architecture Ownership

> Living document. **Who owns what** after the native Nautilus migration.
>
> | Doc | Role |
> |---|---|
> | This file | Ownership, dependency direction, quality gates |
> | [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md) | Modes, forbid list, exits, settlement, reporting constraints |
> | [`NAUTILUS_CAPABILITY_MATRIX.md`](NAUTILUS_CAPABILITY_MATRIX.md) | Verified package capabilities (evidence only) |

## Three truths

| Truth | Owner | Must not own |
|---|---|---|
| **Nautilus Runtime** | `LiveNode`/`BacktestEngine`, DataEngine, ExecutionEngine, RiskEngine, Cache, Portfolio, native Order/Position, Account | Alpha formulas, market discovery rules, report sinks |
| **PolySignal Decision** | `MarketCatalog`, `MarketViewAssembler`, alpha cores, pure in-process `DecisionPolicy` / `SignalGate` (business quals only), native order mapping, read-only Cache allocation rules | Live books, fill/order lifecycle, balances, exposure, portfolio ledger; no DecisionPolicyActor bus; no second RiskEngine |
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
  └─ PolySignalNativeStrategy + PolySignalStrategyConfig
        ├─ DecisionPolicy  (in-process; SignalGate business quals)
        ├─ MarketViewAssembler  ← Cache-backed books + CustomData
        ├─ DecisionPipeline / NativeExitPolicy / native_order
        └─ observability hooks  → Reporting Truth
```

Rules:

1. Decision code does not import venue transports or legacy OrderBook/CLOB stacks.
2. Strategy remains a Nautilus callback host; multi-step business logic lives in collaborators under `nautilus_runtime/strategy/`.
3. Reporting consumes projections only; it never invents open positions or settlement fills.
4. Decision evaluation is in-process on `PolySignalNativeStrategy` via pure `DecisionPolicy` / `SignalGate`; do not reintroduce a DecisionPolicyActor, candidate/approval Signal bus, or a local account/exposure gate that duplicates RiskEngine.
5. Decision timers and event timestamps come from the Nautilus Clock; do not bypass with wall-clock side channels for trading decisions.
6. Python 3.12 and the exact Nautilus dependency are required.

Registration surface, mode gates, exits, settlement, and reporting storage rules live in
[`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md).

## Accepted boundaries (do not “fix”)

These are intentional product/domain seams, not debt:

- `MarketCatalog` business-key boundary (condition/token → instrument id)
- `MarketViewAssembler` pure domain projection
- `Side` UP/DOWN vs Nautilus `OrderSide`; `OrderIntent` vs `TimeInForce`
- `native_order` thin mapping (`order_factory` + `submit_order` only)
- `SignalGate` as business eligibility policy (not RiskEngine; no cross-strategy arbiter bus)
- Settlement **report-only** for sandbox/live; backtest may replay native
  `InstrumentClose` (see Runtime Boundary)
- RTDS spot via LiveDataClient only; SIDECAR vs RTDS client-id separation
- `NativeExitPolicy` over Cache positions (sandbox reduce-only; live venue narrower)
- Report projections never feed trading decisions; SQLite/JSONL use `report_*` names
- Strategy custom state = research state or immutable intent only; Cache reconstructs in-flight management

## False-positive traps

High CBO/LCOM on Strategy/Actor/policy hubs is often framework-shaped or desirable fan-in. Metrics alone are not ownership failures.

## Locked version

Executable API truth: installed and locked
`nautilus_trader[polymarket]==1.231.0a20260716`.
`docs/nautilus_reference/` is reference material, not a version lock.
Verified capability rows: [`NAUTILUS_CAPABILITY_MATRIX.md`](NAUTILUS_CAPABILITY_MATRIX.md).

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
