# Architecture Ownership

> Living document. Ownership and dependency direction after the non-production Nautilus architecture cutover (2026-07-12).
>
> Companion: [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md)

## Three truths

| Truth | Owner | Must not own |
|---|---|---|
| **Nautilus Runtime** | `TradingNode`, DataEngine, ExecutionEngine, Cache, Portfolio, Position, Account, sandbox fills | Alpha formulas, market discovery rules, report sinks |
| **PolySignal Decision** | `MarketCatalog`, `MarketViewAssembler`, alpha cores, `DecisionPolicy` (gate/arbiter/consensus), native order mapping, reduce-only exit policy, project pre-trade constraints over Cache | Live books, order lifecycle, portfolio ledger |
| **Reporting** | SQLite/JSONL, Telegram, dashboard projections, report-only settlement | Trading state mutation |

Any module that is not one of these three either becomes a collaborator of one truth or is quarantined/deleted.

## Dependency direction

```
TradingNode
  ├─ PolymarketLiveDataClientFactory / SandboxLiveExecClientFactory
  ├─ RTDS LiveDataClient (managed spot, single source)
  ├─ MarketRotationActor  (universe / metadata / PTB CustomData; no RTDS spot republish)
  ├─ NautilusDecisionPolicyActor  (thin Actor lifecycle over pure DecisionPolicy)
  └─ PolySignalNativeStrategy  (thin callback host)
        ├─ MarketViewAssembler  ← Cache-backed books + CustomData
        ├─ DecisionPolicy       ← shared injection only
        ├─ DecisionPipeline / NativeExitPolicy / native_order
        └─ observability hooks  → Reporting Truth
```

Rules:

1. Decision code does not import venue transports or legacy OrderBook/CLOB stacks.
2. Strategy remains a Nautilus callback host; multi-step business logic lives in collaborators under `nautilus_runtime/strategy/`.
3. Reporting consumes projections only; it never invents open positions or settlement fills.
4. Optional Nautilus install boundary is preserved (`uv sync --extra nautilus --python 3.12`).

## Accepted boundaries (do not “fix”)

- `MarketCatalog` business-key boundary (condition/token → instrument id)
- `MarketViewAssembler` pure domain projection
- `Side` UP/DOWN vs Nautilus `OrderSide`
- `OrderIntent` vs `TimeInForce`
- `native_order` thin mapping (`order_factory` + `submit_order` only)
- `SignalGate` / consensus / arbitration as business policy (not RiskEngine)
- Settlement is **report-only** under NautilusTrader 1.229.0
- RTDS spot via LiveDataClient only; SIDECAR vs RTDS client-id separation
- `NativeExitPolicy` over Cache positions (reduce-only)

## False-positive traps

High CBO/LCOM on Strategy/Actor/policy hubs is often framework-shaped or desirable fan-in. Metrics alone are not ownership failures.

## Locked version

Executable API truth: installed and locked `nautilus_trader[polymarket]==1.229.0`.
`docs/nautilus_reference/` is reference material, not a version lock.
