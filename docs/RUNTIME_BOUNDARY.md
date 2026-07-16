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
- `src/polysignal_lab/alpha/`

## Sandbox / paper defaults

- Sandbox book type remains L2-aligned with current config (`sandbox_book_type`).
- Pre-trade project constraints may read Cache open state; they do not invent a portfolio ledger.
- Reduce-only exits derive from Cache positions.

## Exit ownership (accepted)

- **Sole paper exit authority:** `NativeExitPolicy` over Nautilus Cache open positions.
- Exits submit **reduce-only** orders via `order_factory` + `submit_order` only.
- Sandbox keeps `support_contingent_orders=False` and `use_reduce_only=True`. PolySignal does **not** attach Nautilus bracket / contingent TP-SL child orders under locked 1.229.0.
- **Threshold precedence (per open position):**
  1. Entry-time stamps on the position (`tp_sl_tp_prob` / `tp_sl_stop_prob` from ptb_diff, or `flip_stop_price` when `flip_stop_enabled` from late_consensus), bound into a strategy-local map on entry fill and also tagged on entry orders as `exit_tp_price` / `exit_stop_price`. Stamps clear only when the Cache position is **fully closed** (not on partial reduce-only fills).
  2. Else global `paper_trading.exit_model` prices (`take_profit_price`, `stop_loss_price`).
  3. `max_hold_time_sec` remains **global** only (not stamped per entry).
- Global enable flags (`take_profit_enabled` / `stop_loss_enabled`) still gate whether TP/SL fire; only the **price levels** are per-position when stamped.
- Strategy YAML exit knobs must not create a second exit engine — they only supply threshold stamps consumed by `NativeExitPolicy`.
- Early TP/SL/max-hold closes write Reporting Truth `paper_trade_results` with `exit_mode` ∈ {`TAKE_PROFIT`,`STOP_LOSS`,`MAX_HOLD_TIME`}. Market-resolution settlement remains report-only and does not fabricate Nautilus `PositionClosed`.
- Early-exit durable results also take the same best-effort Telegram path as resolution settlement (`ObservabilityService.notify_paper_result` → `PublishService.publish_paper_result`) when `telegram.send_paper_results` is true. Publish failure must not roll back the durable write.

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
