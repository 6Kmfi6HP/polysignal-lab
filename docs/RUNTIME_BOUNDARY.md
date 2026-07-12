# Runtime Boundary

> Living document. Runtime forbid-list, sandbox defaults, and report-only constraints after the architecture cutover (2026-07-12).
>
> Companion: [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md)
>
> Historical migration/review notes live under `docs/archive/` and are not current requirements.

## Runtime surface

- Entry: `TradingNode` + `TradingNodeConfig` (not legacy `LiveNode.builder`).
- Data: official Polymarket live data client factory.
- Execution: sandbox execution client factory only; live Polymarket execution stays disabled.
- Orders: `order_factory` + `submit_order` only.
- Books/ticks: Nautilus `Cache` is the only live authority for MarketView books.
- MarketView assembly: Cache-backed provider bound after Cache exists; fail closed when books are missing. No `OrderBookRegistry` fallback.
- Spot: managed RTDS `LiveDataClient` is the single source; MarketRotation must not republish RTDS spot.
- CustomData routing: SIDECAR and RTDS client ids stay separated.

## Composition rules

1. Construct `MarketCatalog` + unbound Cache-backed books provider at projection setup.
2. After trader registration and `node.build()`, bind the real Nautilus Cache once.
3. Do not leave an empty-book bootstrap on the live path as a permanent second provider type.
4. Shared `DecisionPolicy` injection is mandatory for strategies.
5. Pure policy class name is `DecisionPolicy`. Optional `NautilusDecisionPolicyActor` is only the thin Nautilus lifecycle adapter.

## Forbid list (live / decision / trading paths)

Runtime, bridge decision wiring, and signal-policy code must not reattach:

| Surface | Why |
|---|---|
| `OrderBookRegistry` / domain live book registry as decision truth | Second book truth |
| Standalone CLOB REST/WS clients as live book feeds | Bypasses DataEngine |
| Local paper executors / matching engine / wallet ledger | Second execution truth |
| Fabricated settlement fills / `PositionClosed` / Portfolio mutation | Unsupported in 1.229.0 |
| Live Polymarket execution client factories | Lab remains paper-safe |
| Dynamic runtime class factories / reverse instrument registries | Ownership dilution |

Enforcement: `scripts/safety_scan.py`, `tests/test_safety.py`, `tests/test_nautilus_platform_boundary.py`, `tests/test_nautilus_safety_boundary.py`.

Legacy OrderBook/CLOB modules may remain only as non-live residue for tests or quarantined adapters. They must not be imported from:

- `src/polysignal_lab/nautilus_runtime/`
- `src/polysignal_lab/nautilus_bridge/` (except accepted anchor/spot helpers that are not book truth)
- `src/polysignal_lab/signal_layer/`

## Sandbox / paper defaults

- Sandbox book type remains L2-aligned with current config (`sandbox_book_type`).
- Pre-trade project constraints may read Cache open state; they do not invent a portfolio ledger.
- Reduce-only exits derive from Cache positions.

## Settlement

`native_settlement_mode=report_only`. No public payout/redeem authority in locked 1.229.0. Do not synthesize fills or closed positions from Gamma/WS/chain resolution into Nautilus state.

## Verification seams (only these three)

1. **Node composition** — Cache-backed MarketView books; no empty live bootstrap.
2. **Safety / import boundary** — dual-path and second-execution symbols blocked.
3. **Decision + strategy behavior** — rename/extraction preserve gate, order map, reduce-only exits.

## Optional dependency

```bash
uv sync --extra nautilus --python 3.12
```

Default Python 3.11 core install must not hard-require Nautilus where the project already isolates it.
