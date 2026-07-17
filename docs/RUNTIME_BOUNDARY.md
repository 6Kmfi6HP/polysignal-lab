# Runtime Boundary

> Living document. Runtime ownership, safe composition, and reporting constraints after the native migration.
>
> Companion: [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md)
>
> Historical migration/review notes live under `docs/archive/` and are not current requirements.

## Trading modes

| Mode | Data | Execution | Reconciliation | Live factory |
|---|---|---|---|---|
| `sandbox` | Official Polymarket data + optional managed RTDS | Nautilus sandbox execution | Off | Never registered |
| `live` | Official Polymarket data + optional managed RTDS | Official Polymarket execution | On | Registered only after all gates pass |
| `backtest` | Historical native market data and the same CustomData types | Native BacktestEngine matching | Off | Never imported or registered |

The default is `sandbox`. `live` requires `execution_mode=live`,
`allow_live_polymarket_execution=true`,
`safety.allow_live_market_actions=true`, complete credentials, and successful
configuration validation. Any missing condition fails before node construction.

All modes register the same `PolySignalNativeStrategy` and frozen,
JSON-serializable `PolySignalStrategyConfig`; mode differences end at node,
data client, execution client, and historical input composition.

## Runtime surface

- Node composition uses the latest pyo3 `LiveNode.builder` or `BacktestEngine`.
- Nautilus Cache, Portfolio, Account, native Order/Position, ExecutionEngine, and
  RiskEngine are the only trading facts.
- Orders enter through `order_factory` and `submit_order` only.
- MarketView books and positions are Cache projections and fail closed when absent.
- RTDS is a managed `LiveDataClient`; MarketRotation publishes only immutable
  universe, metadata, and price-to-beat CustomData.
- Candidate and approval traffic uses immutable native Signal messages between
  the Strategy and the sole `DecisionPolicyActor` owner.
- All decision timers and event timestamps come from Nautilus Clock.

## Forbid list (live / decision / trading paths)

Runtime, bridge decision wiring, and signal-policy code must not reattach:

| Surface | Why |
|---|---|
| `OrderBookRegistry` / domain live book registry as decision truth | Second book truth |
| Standalone CLOB REST/WS clients as live book feeds | Bypasses DataEngine |
| Local paper executors / matching engine / wallet ledger | Second execution truth |
| Fabricated settlement fills / `PositionClosed` / Portfolio mutation | No public sandbox/live settlement authority |
| Ungated live Polymarket execution client factories | Live must remain fail closed |
| Dynamic runtime class factories / reverse instrument registries | Ownership dilution |

Enforcement: `scripts/safety_scan.py`, `tests/test_safety.py`, `tests/test_nautilus_platform_boundary.py`, `tests/test_nautilus_safety_boundary.py`.

Migration quality gates (pytest, safety, basedpyright baseline, live-off default)
are defined in [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md#quality-gates-native-migration-complete).

## Sandbox defaults

- Sandbox book type remains L2-aligned with current config (`sandbox_book_type`).
- Pre-trade project constraints may read Cache open state; they do not invent a portfolio ledger.
- Reduce-only exits derive from Cache positions.

## Exit ownership (accepted)

- `NativeExitPolicy` reads Nautilus Cache open positions and submits native exits.
- Exits submit **reduce-only** orders via `order_factory` + `submit_order` only.
- Sandbox keeps `support_contingent_orders=False` and `use_reduce_only=True`.
- **Threshold precedence (per open position):**
  1. Entry order tags `exit_tp_price` and `exit_stop_price`, rebuilt from Cache orders.
  2. Global `trading.exit_model` prices.
  3. `max_hold_time_sec` remains **global** only (not stamped per entry).
- Threshold tags express intent only; quantities, fills, open/closed state, and PnL
  always come from Cache and native events.
- Early exits create `report_results` projections after native execution events.
  Reporting or Telegram failures cannot roll back or advance trading state.

## Settlement

`native_settlement_mode=report_only` for sandbox and live. The verified latest
adapter has resolution data and polling but no public payout, redeem, or settle
authority. Gamma, WS, chain, or `InstrumentClose` observations must not
synthesize fills, positions, Portfolio, Account, or Cache mutation.

The pyo3 `BacktestEngine` is narrower and has a verified native
`InstrumentClose(CONTRACT_EXPIRED)` path: its simulated matching engine creates
the expiration order/fill and updates Position, Cache, Portfolio, and Account.
PolySignal may replay that data event in backtest, but must not reproduce the
mutation itself.

## Registration and policy ownership

The latest pyo3 API provides native Signal publish/subscribe. Importable config
registration creates one `DecisionPolicyActor` and one Strategy instance; no
registration global, staged object copy, or local MessageBus remains. Candidate
batches are immutable and the Actor publishes immutable approval/rejection
results. See [`NAUTILUS_CAPABILITY_MATRIX.md`](NAUTILUS_CAPABILITY_MATRIX.md).

## Reporting boundary

- SQLite tables use `report_*` names and are disposable read projections.
- JSONL, Telegram, and Dashboard consume reporting rows only.
- Schema migration backs up a database before converting legacy tables.
- Runtime never restores orders, fills, positions, exposure, reservations, or
  account values from reporting storage.
- Deleting reporting storage may remove display history but cannot change the
  Strategy, RiskEngine, reconciliation, orders, or positions.

## Verification seams (only these three)

1. **Node composition** — Cache-backed MarketView books; no empty live bootstrap.
2. **Safety / import boundary** — dual-path and second-execution symbols blocked.
3. **Decision + strategy behavior** — rename/extraction preserve gate, order map, reduce-only exits.

## Runtime dependency

```bash
uv sync --python 3.12
```

Python 3.12 and the exact Nautilus package version in `pyproject.toml` are
required runtime contracts.
