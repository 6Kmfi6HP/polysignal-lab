# NautilusTrader capability matrix

> Living document. **Verified package capabilities only** (not ownership or
> runtime policy). Those live in [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md)
> and [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md).

Verified on Python 3.12 against the installed and locked
`nautilus_trader[polymarket]==1.231.0a20260716` package. Evidence comes
from installed code, public signatures, and executable local probes. It is not
live venue acceptance evidence.

| Capability | Verified evidence | Status | Implementation decision |
|---|---|---|---|
| Polymarket live data | Official `PolymarketDataClientFactory` and config imports construct | Supported | Use the official data factory in sandbox and live |
| Polymarket live execution | Official `PolymarketExecutionClientFactory` and exec config construct | Composition supported | Register only in explicit live mode after both safety switches and credential validation |
| Live registration | Builder exposes data, simulated-exec, and live-exec registration; node exposes importable Actor/Strategy configs | Supported by serialized config | Register one `MarketRotationActor` and one `PolySignalNativeStrategy` config; no `DecisionPolicyActor` |
| Native Actor/Strategy messaging | `publish_signal` and `subscribe_signal` complete a real BacktestEngine roundtrip; `Signal` is immutable | Supported (engine) | Not used for candidate/approval; decision path is in-process `DecisionPolicy` on Strategy |
| CustomData | Latest Strategy/Actor expose `publish_data` and `subscribe_data`; pyo3 `DataType` accepts registered type names | Supported for subscriptions | Universe/metadata/PTB and RTDS use native data subscriptions; policy stays in-process on Strategy |
| Sandbox execution | Official sandbox execution factory/config construct | Supported | Sandbox uses simulated execution, reconciliation off, and never registers live execution |
| Backtest composition | `BacktestEngine` accepts instruments, market data, CustomData, and `InstrumentClose` | Supported | Backtest imports no live transport and reuses the same Strategy/config schema |
| Backtest expiry semantics | Probe observed native expiration order/fill, Position close, Cache/Portfolio flatten, and Account update | Supported by native matching engine | Replay `InstrumentClose` as data; never reproduce these mutations in PolySignal |
| Sandbox/live settlement | No public authenticated payout, redeem, or settle authority exists on the inspected adapter surface | Unsupported | Resolution is report-only; Nautilus exposure remains unchanged unless its own execution/account engine changes it |
| Resolution polling | Public config exposes enable, interval, grace, and max-wait settings | Supported | Use the official watchlist/poll data path |
| Manual resolution request | No public `PolymarketResolveRequest` exists | Unsupported | Do not invent a manual settlement or mutation path |
| Reconciliation | Official live adapter implements order/fill/position status reports | Adapter-supported, live E2E not run | Enable only for authenticated live execution; sandbox and backtest keep it off |
| OrderList/contingency/stops | Native Strategy and OrderFactory expose order lists, bracket/stop factories, contingency and emulation fields | Engine surface supported; venue support narrower | Keep contingent orders disabled for Polymarket until venue acceptance evidence exists |
| Reduce-only | Sandbox supports reduce-only; Polymarket live execution declares it unsupported | Sandbox-only | Sandbox exits may be reduce-only; live cannot claim this behavior |
| Risk limits | `LiveRiskEngineConfig` exposes submit/modify rates and exact-instrument decimal `max_notional_per_order` | Supported subset | Use native rate/notional controls; keep allocation as read-only business policy |
| Data catalog for recording | Probe wrote and re-queried `PolySignalPriceToBeatData` and pyo3 `QuoteTick` through `ParquetDataCatalog`; pyo3 `InstrumentClose` and `PolymarketRtdsCryptoPrice` both raise `TypeError: Cannot serialize object ... Register a serialization method via register_arrow()`. The arrow encoder registry holds the **Cython** `InstrumentClose`, not the pyo3 class the runtime emits | Partial — insufficient for the recorded stream | Keep the local append-only JSONL `RecordedMarketDataStore`. Recording must cover `InstrumentClose` (backtest settlement rounds) and RTDS spot, so the catalog cannot carry the stream until those pyo3 types get `register_arrow()` coverage |
| Node shutdown on OS signals | `LiveNode.run()` documents "Run the live node with automatic shutdown handling"; `start()` documents "Starts the live node without entering a select loop". The runtime drives `run()` (`node_lifecycle.py:_run_node_async`) inside `asyncio.to_thread`, racing it against an `asyncio.Event` so a stop request can call `stop()` | Supported | Let `run()` own shutdown. `runtime.nautilus.intercept_os_signals` defaults to `false` (`config.py:292`, and `false` in both `config/signal_bot.yaml` and `config/signal_bot.lab.yaml`), so the project SIGTERM/SIGINT handlers in `node_signals.py` install only where an operator explicitly opts in — they are an escape hatch, not a replacement |

## Probe boundary

No private credential was loaded, no private account or production network was
connected, and no live order, redemption, or real-funds workflow was executed.
Live results therefore mean composition and fail-closed safety only.
