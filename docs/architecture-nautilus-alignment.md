# Architecture Design: Aligning PolySignal Lab with NautilusTrader Polymarket Adapter

> **Status:** Design Proposal  
> **Date:** 2026-07-08  
> **Scope:** Assessment of existing custom implementations and a phased migration plan toward alignment with the official `nautilus_trader.adapters.polymarket` API.

---

## Section 1: Correctness Assessment

This section evaluates every custom implementation in the PolySignal Lab codebase against the official NautilusTrader Polymarket adapter conventions. Each assessment is based on source-code analysis of both the project and the documented Nautilus adapter API.

### 1.1 Correct Implementations (Keep As-Is)

| Component | File | Verdict | Rationale |
|---|---|---|---|
| `Side` enum (UP/DOWN) | `src/polysignal_lab/domain/enums.py` | **Keep** | This is a Polymarket domain concept (outcome selection), not a Nautilus order-side concept. Nautilus's `OrderSide.BUY/SELL` describes the _action_ on a specific instrument. Since each Polymarket token is a separate `BinaryOption` instrument, buying UP is always `OrderSide.BUY` of instrument_A -- there is no Nautilus `OrderSide.UP`. The custom `Side` enum is essential and correct. |
| `native_order.py` side mapping | `src/polysignal_lab/nautilus_runtime/native_order.py` | **Keep** | The `_order_side()` function correctly maps both `Side.UP` and `Side.DOWN` to `OrderSide.BUY` (lines 86-91). For reduce-only orders it maps to `OrderSide.SELL`. This is exactly correct per Nautilus adapter semantics. |
| `instrument_mapping.py` | `src/polysignal_lab/nautilus_bridge/instrument_mapping.py` | **Keep** | Wraps `get_polymarket_instrument_id()` from the official adapter with lazy import and error handling. This is the recommended pattern and already implemented. |
| `MarketCatalog` | `src/polysignal_lab/nautilus_bridge/market_catalog.py` | **Keep (minor extension)** | Uses `condition_id` + `token_id` as business keys, which is the correct abstraction boundary. The `instrument_id_for_token()` method correctly delegates to the resolver. The catalog should _not_ be replaced -- but can be extended to surface `BinaryOption` properties (see Section 2). |
| `MarketViewAssembler` | `src/polysignal_lab/nautilus_bridge/market_view_assembler.py` | **Keep** | Correctly assembles a prediction-market-specific view from Nautilus cache projections + custom data. This is _pure domain logic_ Nautilus doesn't provide. |
| `OrderIntent` enum | `src/polysignal_lab/domain/enums.py` | **Keep** | Polysignal-specific order routing semantics (PASSIVE_GTD, TAKER_FOK, TAKER_FAK, TAKER_IOC). Nautilus has `TimeInForce.GTD/FOK/IOC` but no concept of "intent" with expiry-second defaults and pair routing. |
| `native_order.py` TIF mapping | `src/polysignal_lab/nautilus_runtime/native_order.py` | **Keep** | `_time_in_force()` correctly maps OrderIntent to `TimeInForce` values (lines 93-99). |

### 1.2 Incorrect or Suboptimal Implementations (Should Align)

| Component | File | Issue | Recommendation |
|---|---|---|---|
| `OrderBook` model | `src/polysignal_lab/domain/orderbook.py` | Duplicates `OrderBookSnapshot`/`OrderBookDeltas` from Nautilus. The Pydantic model with `from_polymarket()` parser pre-dates the Nautilus data ingestion layer. Now that the runtime uses `PolymarketLiveDataClientFactory` (per NAUTILUS_BRIDGE_BOUNDARY.md), Nautilus already manages order-book state. | Move raw Polymarket order-book ingestion to the Nautilus boundary. Keep a _simplified_ custom `OrderBook` only for the `MarketView` assembly layer. |
| `PaperOrder` / `PaperFill` | `src/polysignal_lab/domain/paper_order.py` | These duplicate Nautilus order types (`Order`, `OrderFilled` event). The project has already migrated to `SandboxLiveExecClientFactory` for paper execution. `PaperOrder` is now legacy scaffolding used only in the execution test suite. | Replace with Nautilus `Order` types in paper execution. Retain `PaperOrder` only as a serialization DTO if test assertions depend on it (see Section 3). |
| `PaperPosition` | `src/polysignal_lab/domain/paper_position.py` | Duplicates Nautilus `Position` class with custom `PositionStatus` enum. Nautilus already tracks position lifecycle through its portfolio. | Replace with Nautilus `Position` for runtime state. Keep `PaperPosition` only for dashboard/report serialization if needed. |
| Custom `OrderStatus` enum | `src/polysignal_lab/domain/enums.py` | Defines PENDING/FILLED/REJECTED/RESTING/CANCELLED/PARTIAL -- overlaps significantly with `nautilus_trader.model.enums.OrderStatus`. | Replace with Nautilus `OrderStatus` in paper/runtime code that touches Nautilus-managed state. Keep the custom enum only for test fixtures or domain-specific status aggregation. |
| Custom `PositionStatus` enum | `src/polysignal_lab/domain/enums.py` | OPEN/CLOSED -- duplicates `nautilus_trader.model.enums.PositionStatus`. | Replace with Nautilus `PositionStatus` at the Nautilus boundary. |
| `Market.from_gamma()` | `src/polysignal_lab/domain/market.py` | Parses raw Polymarket API JSON manually with 280+ lines of bespoke field extraction and outcome-token heuristics. Nautilus provides `parse_polymarket_instrument()` for this. | Align to use `parse_polymarket_instrument()` for the `BinaryOption` creation path, wrapping its output with PolySignal-specific enrichment (asset, timeframe, price_to_beat). |
| Custom `MarketStatus` enum | `src/polysignal_lab/domain/enums.py` | Defines its own market lifecycle enum (ACTIVE/CLOSED/RESOLVED/CANCELLED/UNKNOWN). Nautilus does NOT have a `MarketStatus` equivalent; this is a Polymarket domain concept. | **Borderline.** This is correct Polymarket domain logic, but the status-resolution logic in `_status_from_gamma()` should ideally use Nautilus's adapter conventions if available. Keep as-is for now. |

### 1.3 Summary Assessment

The codebase is _structurally sound_ but has a boundary-blur issue: domain models (`Market`, `OrderBook`) are doing double duty as both API-parsing DTOs and runtime models. The Nautilus bridge boundary (documented in `NAUTILUS_BRIDGE_BOUNDARY.md`) already established that Nautilus owns data ingestion and execution. The remaining alignment work is about:

1. Pushing raw API parsing to the Nautilus adapter boundary
2. Replacing duplicated state models with Nautilus equivalents
3. Adding enum parsers for type-safe Nautilus<->Polysignal conversion

---

## Section 2: Safe Alignment Opportunities

These changes are low-risk, backwards-compatible, and can be done independently without breaking existing functionality.

### 2.1 Widen Adoption of `get_polymarket_instrument_id()`

**Current state:** `src/polysignal_lab/nautilus_bridge/instrument_mapping.py` already wraps `get_polymarket_instrument_id()` with lazy import. The `MarketCatalog.instrument_id_for_token()` method delegates to it.

**Opportunity:** The function is currently only used through `MarketCatalog`. Call sites that construct `InstrumentId` directly (e.g., `native_order.py`'s `_instrument_id()` helper) should route through the shared resolver.

**Specific change:**

In `src/polysignal_lab/nautilus_bridge/market_catalog.py`, the resolver pattern is already correct:

```python
def instrument_id_for_token(self, token_id: str) -> str | None:
    pair = self.by_token(token_id)
    if pair is None:
        return None
    resolver = self._instrument_id_resolver or polymarket_instrument_id
    return resolver(pair.condition_id, token_id)
```

**Action:** Ensure all `InstrumentId` construction in `native_order.py` goes through `MarketCatalog.instrument_id_for_token()` rather than ad-hoc string formatting.

### 2.2 Surface `BinaryOption` Properties Through `MarketCatalog`

**Current state:** `MarketCatalog` stores tokens as `InstrumentTokenMeta` (just `token_id` + `side`). It does not expose Nautilus `BinaryOption` instrument properties like `outcome`, `description`, `expiry`, or `price_precision`.

**Opportunity:** When a `BinaryOption` instrument is loaded by the Nautilus data client, its properties can be associated with the catalog entry for richer MarketView assembly (e.g., passing `outcome` names, expiry timestamps).

**Specific change in `src/polysignal_lab/nautilus_bridge/market_catalog.py`:**

```python
@dataclass(frozen=True, slots=True)
class InstrumentTokenMeta:
    token_id: str
    side: Side
    outcome: str | None = None        # e.g., "Yes", "Up"
    description: str | None = None    # e.g., "Will ETH > $5000 by Dec 2026"
    expiry: datetime | None = None    # from BinaryOption.activation/expiration
```

This is purely additive -- existing code that constructs `InstrumentTokenMeta` without these fields continues to work.

### 2.3 Adopt `parse_polymarket_instrument()` in `Market.from_gamma()`

**Current state:** `src/polysignal_lab/domain/market.py` `Market.from_gamma()` manually extracts fields from raw Polymarket API JSON (lines 78-140). This is fragile: field names change, outcome token detection has heuristics, and resolution-status logic is bespoke.

**Opportunity:** Use the Nautilus adapter's `parse_polymarket_instrument()` to convert raw JSON into a `BinaryOption` instrument, then extract what the `Market` model needs from the typed `BinaryOption` instance.

**Conceptual change:**

```python
from nautilus_trader.adapters.polymarket import (
    parse_polymarket_instrument,
    get_polymarket_instrument_id,
)

@classmethod
def from_gamma(cls, payload, asset, timeframe):
    # Let Nautilus parse the instrument
    instrument = parse_polymarket_instrument(payload)
    # instrument is a BinaryOption with properties:
    #   .id, .outcome, .description, .activation, .expiration
    #   .price_precision, .size_precision
    # Now enrich with Polysignal-specific fields
    return cls(
        market_id=...,
        condition_id=...,
        price_to_beat=payload.get("priceToBeat"),
        # ... Polysignal-specific enrichment ...
    )
```

**Caveat:** `parse_polymarket_instrument()` expects a specific JSON shape that may differ slightly from the Gamma API response the project uses. This requires verification against the actual Polymarket endpoint data the project ingests. Start by testing `parse_polymarket_instrument()` against a sample Gamma payload in the test suite.

### 2.4 Add `PolymarketEnumParser`

**Current state:** Conversions between Polysignal enums and Nautilus enums are scattered across `native_order.py` (`_order_side()`, `_time_in_force()`), `order_plan.py`, and inline in strategies.

**Opportunity:** Create a centralized `PolymarketEnumParser` following the Nautilus adapter pattern (seen in Binance, Bybit, OKX adapters: each has an `EnumParser` class).

**New file:** `src/polysignal_lab/nautilus_bridge/enum_parser.py`

```python
from __future__ import annotations

from nautilus_trader.model.enums import OrderSide, OrderStatus, TimeInForce

from polysignal_lab.domain.enums import OrderIntent, Side


class PolymarketEnumParser:
    """Type-safe enum conversion between PolySignal domain enums and Nautilus enums."""

    @staticmethod
    def to_nautilus_order_side(side: Side, *, reduce_only: bool = False) -> OrderSide:
        """Map Polysignal Side to Nautilus OrderSide."""
        if reduce_only:
            return OrderSide.SELL
        # Each Polymarket token is a separate BinaryOption instrument,
        # so buying UP or DOWN is always OrderSide.BUY.
        if side in {Side.UP, Side.DOWN}:
            return OrderSide.BUY
        raise ValueError(f"Unsupported side: {side}")

    @staticmethod
    def to_nautilus_time_in_force(intent: OrderIntent) -> TimeInForce:
        if intent == OrderIntent.PASSIVE_GTD:
            return TimeInForce.GTD
        if intent == OrderIntent.TAKER_FOK:
            return TimeInForce.FOK
        return TimeInForce.IOC

    @staticmethod
    def to_nautilus_order_status(status: str) -> OrderStatus:
        """Map PolySignal order status string to Nautilus OrderStatus."""
        mapping = {
            "PENDING": OrderStatus.PENDING,
            "ACCEPTED": OrderStatus.ACCEPTED,
            "REJECTED": OrderStatus.REJECTED,
            "CANCELLED": OrderStatus.CANCELED,
            "FILLED": OrderStatus.FILLED,
            "PARTIAL": OrderStatus.PARTIALLY_FILLED,
            "RESTING": OrderStatus.ACCEPTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        return mapping.get(status.upper(), OrderStatus.UNKNOWN)
```

Then refactor `native_order.py` to use `PolymarketEnumParser`:

```python
# Instead of:
def _order_side(side: Side, *, reduce_only: bool) -> object:
    ...
def _time_in_force(intent: OrderIntent) -> object:
    ...

# Use:
order_side = PolymarketEnumParser.to_nautilus_order_side(spec.side)
time_in_force = PolymarketEnumParser.to_nautilus_time_in_force(spec.intent)
```

### 2.5 Quantity Semantics for Market Orders

**Current state:** `src/polysignal_lab/nautilus_runtime/order_plan.py` `resolve_order_quantity()` (which I infer constructs a quantity from `fixed_stake_usdc` / price) does not distinguish between LIMIT and MARKET order quantity semantics.

**Nautilus Polymarket adapter convention:**
- **LIMIT orders:** `quantity` = number of conditional tokens (base units), `quote_quantity=False`
- **MARKET BUY:** `quantity` = quote notional (USDC.e), set `quote_quantity=True` on the order
- **MARKET SELL:** `quantity` = base units

**Opportunity:** Add an `is_market` flag to `NautilusOrderSpec` or detect it from `OrderIntent` (TAKER_FOK/TAKER_FAK/TAKER_IOC imply market semantics). When `is_market` and side is BUY, set `quote_quantity=True`.

**Specific change in `src/polysignal_lab/nautilus_runtime/native_order.py`:**

When submitting a market-buy order, pass `quote_quantity=True`:

```python
# In submit_approved_decision() or a new _submit_market_order():
is_market = spec.intent in {
    OrderIntent.TAKER_FOK, OrderIntent.TAKER_FAK, OrderIntent.TAKER_IOC
}
if is_market and not spec.reduce_only:
    # Use quote_quantity for market BUY
    order = strategy.order_factory.market(
        instrument_id=_instrument_id(instrument),
        order_side=order_side,
        quantity=_quantity_value(instrument, spec.quantity),
        quote_quantity=True,  # Polymarket convention
        tags=[...],
    )
```

This requires that `ExecEngineConfig(convert_quote_qty_to_base=False)` is set in the node config (matching the adapter's documented requirement).

---

## Section 3: Architecture Changes (Medium Term)

These changes require structural refactoring across multiple files. They should be done in a dedicated branch with full test coverage.

### 3.1 Replace `OrderBook` at Data Ingestion Boundary

**Current architecture:**

```
Polymarket API (raw JSON)
  -> from_polymarket() -> domain/orderbook.py OrderBook (Pydantic)
    -> stored in custom data state
      -> MarketViewAssembler builds SideBookView from OrderBook
```

**Target architecture:**

```
Polymarket API (raw JSON)
  -> Nautilus OrderBookSnapshot / OrderBookDeltas (managed by data client)
    -> cached in Nautilus cache
      -> MarketViewAssembler reads via BookDataProvider protocol
        -> SideBookView built from cached snapshot
```

**Why:** Nautilus's `PolymarketLiveDataClientFactory` already registers and maintains order-book state through `OrderBookSnapshot` and `OrderBookDeltas`. The project's `OrderBook` model is a redundant parsing layer.

**What to keep:** A _much_ simpler `SideBookView` builder in `market_view_assembler.py` that extracts bid/ask/spread/freshness from Nautilus cached snapshots. The custom `OrderBook` model should be removed from the domain layer.

**What to add to `MarketViewAssembler`:**

```python
from nautilus_trader.model.data import OrderBookSnapshot, OrderBookDeltas

class BookDataProvider(Protocol):
    def book_for_token(self, token_id: str) -> SideBookView | None: ...
    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...

# Implementation that reads from Nautilus cache:
class NautilusBookProvider:
    def __init__(self, cache: Any, catalog: MarketCatalog):
        self._cache = cache
        self._catalog = catalog

    def book_for_token(self, token_id: str) -> SideBookView | None:
        instrument_id = self._catalog.instrument_id_for_token(token_id)
        if instrument_id is None:
            return None
        snapshot = self._cache.parsed_snapshot(instrument_id)
        if snapshot is None:
            return None
        return self._snapshot_to_view(snapshot)

    def _snapshot_to_view(self, snap: OrderBookSnapshot) -> SideBookView:
        bids = [(float(level.price), float(level.size))
                for level in snap.bids]
        asks = [(float(level.price), float(level.size))
                for level in snap.asks]
        return SideBookView(
            token_id="",
            best_bid=max(bids)[0] if bids else None,
            best_ask=min(asks)[0] if asks else None,
            spread=(min(asks)[0] - max(bids)[0])
                     if bids and asks else None,
            freshness_ms=None,
            ask_levels=tuple(asks),
        )
```

### 3.2 Replace `PaperOrder`/`PaperFill` with Nautilus Types

**Current state:** `PaperOrder` (32 fields) and `PaperFill` (17 fields) are used in the paper execution test suite. The runtime has already moved to `SandboxLiveExecClientFactory`.

**Why change:** The paper execution layer now goes through Nautilus sandbox. `PaperOrder`/`PaperFill` are only kept for test assertions. Nautilus provides:
- `Order` (and subtypes like `LimitOrder`, `MarketOrder`) with full lifecycle
- `OrderFilled` event with fill details
- `OrderStatus` enum for state tracking

**Migration approach:**

1. Replace the paper execution client to work with Nautilus `Order` objects internally
2. Add `to_paper_order()` / `from_paper_order()` conversion methods on the Nautilus `Order` class for backward compat with test assertions
3. Eventually remove `PaperOrder`/`PaperFill` once all tests are migrated

**New converter** in `src/polysignal_lab/nautilus_bridge/order_converter.py`:

```python
from nautilus_trader.model.orders import Order
from polysignal_lab.domain.paper_order import PaperOrder


def nautilus_order_to_paper(order: Order) -> PaperOrder:
    """Convert a Nautilus Order to PaperOrder for test assertions."""
    ...
```

### 3.3 Replace `PaperPosition` with Nautilus `Position`

**Current state:** `PaperPosition` (20 fields) with custom `PositionStatus.OPEN/CLOSED`.

**Why change:** Nautilus `Position` is the canonical runtime representation. It has:
- `InstrumentId`, `side` (OrderSide LONG/SHORT), `quantity`, `avg_px_open`, `realized_pnl`, `unrealized_pnl`
- Position lifecycle events: `PositionOpened`, `PositionAdjusted`, `PositionClosed`
- Portfolio integration for risk checks

**Migration approach:**

1. Map Polymarket outcome tokens to Nautilus `Position` objects
2. Since Nautilus `Position.side` uses `OrderSide.LONG/SHORT` (not PolySignal's UP/DOWN), provide a mapping:
   - UP token LONG = bought UP token
   - UP token SHORT = sold UP token (rare for Polymarket)
   - DOWN token LONG = bought DOWN token
   - DOWN token SHORT = sold DOWN token
3. Retain `PaperPosition` only for dashboard/report serialization

### 3.4 Adopt Nautilus `OrderStatus` and `OrderSide` in Paper/Runtime Code

**Current state:** The runtime has a mix of custom `OrderStatus` (from `domain/enums.py`) and Nautilus `OrderStatus` usage.

**Target state:** All Nautilus-boundary code uses Nautilus enums. Custom enums are used only for:
- Pre-Nautilus domain logic (signal generation, alpha decisions)
- Test fixtures
- Dashboard/report serialization

**Mapping table:**

| Custom (PolySignal) | Nautilus Equivalent |
|---|---|
| `OrderStatus.PENDING` | `OrderStatus.PENDING` |
| `OrderStatus.RESTING` | `OrderStatus.ACCEPTED` |
| `OrderStatus.FILLED` | `OrderStatus.FILLED` |
| `OrderStatus.PARTIAL` | `OrderStatus.PARTIALLY_FILLED` |
| `OrderStatus.CANCELLED` | `OrderStatus.CANCELED` |
| `OrderStatus.REJECTED` | `OrderStatus.REJECTED` |
| `PositionStatus.OPEN` | `PositionStatus.OPEN` |
| `PositionStatus.CLOSED` | `PositionStatus.CLOSED` |

---

## Section 4: Where Custom Code Must Stay

These components are prediction-market-specific or Polysignal-specific. NautilusTrader does not and should not provide equivalents.

### 4.1 `Side` Enum (UP/DOWN)

**File:** `src/polysignal_lab/domain/enums.py`

**Why custom:** Nautilus `OrderSide` is BUY/SELL/LONG/SHORT -- it describes the _action_ on an instrument. `Side.UP/DOWN` is a Polymarket domain concept: which outcome token to buy. Since each token is a separate `BinaryOption` instrument, the mapping `Side.UP/DOWN -> OrderSide.BUY` is fundamental and correct.

**Will never be replaced by Nautilus:** Nautilus's `OrderSide` is venue-agnostic. Polymarket outcome selection is inherently venue-specific.

### 4.2 `OrderIntent` Enum

**File:** `src/polysignal_lab/domain/enums.py`

**Why custom:** Nautilus has `TimeInForce` (GTD, FOK, IOC, GTC, DAY) but no concept of "intent" with the semantics Polysignal needs:
- `PASSIVE_GTD`: limit order with expiry; implies a specific order-routing path
- `TAKER_FAK`: fill-and-kill (partial fill ok)
- `TAKER_FOK`: fill-or-kill (all-or-nothing)
- `TAKER_IOC`: immediate-or-cancel

The `OrderIntent` also carries routing metadata (expiry_seconds, pair_id) that Nautilus doesn't model.

### 4.3 `MarketView` and `MarketViewAssembler`

**Files:**
- `src/polysignal_lab/alpha/types.py` (`MarketView`, `SideBookView`, `FreshnessView`)
- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`

**Why custom:** This is the core value of Polysignal: a prediction-market-specific market view that combines:
- Order-book data for two tokens (UP/DOWN) into a single market view
- Spot price data from external oracles
- Price-to-beat (anchor/liquidation price)
- Freshness metrics across all data sources
- Seconds-to-close and other Polymarket-specific metadata

Nautilus provides raw data primitives (order-book snapshots, trades, quotes) but does not assemble them into a prediction-market view.

### 4.4 Alpha Core Evaluation Pipeline

**File:** `src/polysignal_lab/alpha/` (whole module)

**Why custom:** The alpha core is pure business logic: it evaluates `MarketView` instances and produces `AlphaDecision` objects. It uses Nautilus data _inputs_ but the evaluation logic (signal gating, arbiter, consensus, deduplication) is entirely Polysignal-specific.

### 4.5 Settlement Resolution

**Not yet a separate module (distributed across `Market.from_gamma()`)**

**Why custom:** Polymarket settlement involves chain-specific resolution logic (Gamma API, UMA DVM, CLOB resolution). Nautilus's adapter may provide raw resolution events, but the interpretation (void outcome detection, tie handling, win/loss determination) is Polysignal domain logic.

### 4.6 Signal Layer (Gate, Arbiter, Consensus, Deduper)

**Files in signal_layer/**

**Why custom:** These are Polysignal's risk-management and signal-quality components. Nautilus has no equivalent for:
- Signal gating (freshness, price-to-beat, confidence thresholds)
- Arbiter (conflict resolution between signals)
- Consensus (multi-signal aggregation)
- Deduplication (avoiding redundant signal submission)

### 4.7 Telemetry and Observability

**Files:** `src/polysignal_lab/observability/`, `src/polysignal_lab/nautilus_runtime/telemetry_writer.py`

**Why custom:** Telegram QA, safety scans, dashboard metrics, and event logging are all Polysignal-specific. Nautilus provides `InstrumentStatus` events but no Polymarket-specific observability.

---

## Section 5: Migration Path

### Phase 1: Enum Parser and Instrument ID Alignment (Current Sprint)

**Goal:** Centralize enum conversions and widen instrument ID adoption without breaking changes.

**Files to create:**
- `src/polysignal_lab/nautilus_bridge/enum_parser.py` (new)

**Files to modify:**
- `src/polysignal_lab/nautilus_runtime/native_order.py` -- refactor to use `PolymarketEnumParser`
- `src/polysignal_lab/nautilus_runtime/order_plan.py` -- refactor to use `PolymarketEnumParser` where applicable

**Test impact:** All existing tests continue to pass. Add unit tests for `PolymarketEnumParser`.

**Risks:** None. The enum parser is purely additive.

**Success criteria:**
- `PolymarketEnumParser` has unit tests covering all enum conversions
- `native_order.py` no longer has inline `_order_side()` / `_time_in_force()` (delegates to parser)
- `git diff` shows zero behavioral changes

### Phase 2: `BinaryOption` Properties in `MarketCatalog` (Next Sprint)

**Goal:** Surface Nautilus `BinaryOption` properties through the catalog for richer view assembly.

**Files to modify:**
- `src/polysignal_lab/nautilus_bridge/market_catalog.py` -- extend `InstrumentTokenMeta` with `outcome`, `description`, `expiry`
- `src/polysignal_lab/nautilus_runtime/strategy_builder.py` or equivalent -- populate `InstrumentTokenMeta` from `BinaryOption` data when available

**Test impact:** Existing catalog tests pass unchanged. New tests verify property population.

**Risks:** Low. Additive change to dataclass. Any code that destructures `InstrumentTokenMeta` by position will break (use keyword-only construction which is already the pattern).

**Success criteria:**
- `InstrumentTokenMeta` includes `outcome` and `expiry` fields
- Catalog entries populated from `BinaryOption` instruments include these fields
- No code that constructs `InstrumentTokenMeta` is positional

### Phase 3: Paper Trading Alignment (Medium Term)

**Goal:** Replace `PaperOrder`/`PaperFill`/`PaperPosition` with Nautilus equivalents in the runtime, keeping DTOs only for test assertions and serialization.

**Files to create:**
- `src/polysignal_lab/nautilus_bridge/order_converter.py` -- Nautilus Order <-> PaperOrder converters
- `src/polysignal_lab/nautilus_bridge/position_converter.py` -- Nautilus Position <-> PaperPosition converters

**Files to modify:**
- `src/polysignal_lab/domain/paper_order.py` -- deprecate or isolate to test support
- `src/polysignal_lab/domain/paper_position.py` -- deprecate or isolate to test support
- `src/polysignal_lab/nautilus_runtime/native_strategy.py` -- use Nautilus Position for runtime tracking
- Paper execution client -- use Nautilus order types internally

**Test impact:** Execution tests need updates to work with Nautilus types. This is the highest-risk phase.

**Risks:** Medium. Test fixtures that construct `PaperOrder`/`PaperFill` directly will break. Converter functions must be correct.

**Success criteria:**
- Paper execution produces Nautilus `Order` objects internally
- `PaperOrder` is only constructed through `nautilus_order_to_paper()` for test assertions
- All execution tests pass with the new converter-based approach

### Phase 4: Order-Book at Data Ingestion Boundary (Long Term)

**Goal:** Let Nautilus manage order-book state from Polymarket data. Simplify `OrderBook` model to just what `MarketView` assembly needs.

**Files to modify:**
- `src/polysignal_lab/domain/orderbook.py` -- strip to minimal `BookLevel` +
- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py` -- add `NautilusBookProvider`
- Custom data state -- remove `OrderBook` storage, read from Nautilus cache instead

**Deprecated files (eventually):**
- `domain/orderbook.py` `OrderBook.from_polymarket()` -- no longer needed

**Test impact:** High. Any test that constructs `OrderBook` from raw Polymarket payloads needs to use Nautilus snapshots instead.

**Risks:** High. This changes the data ingestion architecture. Requires thorough verification that Nautilus cache contains the expected order-book state.

**Success criteria:**
- `MarketViewAssembler` reads book data from Nautilus cache via `NautilusBookProvider`
- Custom `OrderBook.from_polymarket()` is unreferenced dead code (removed)
- All integration tests pass with Nautilus-managed order-book state

---

## Dependency Graph of Changes

```
Phase 1 (Enum Parser)
  |
  v
Phase 2 (BinaryOption in Catalog)
  |
  v
Phase 3 (Paper Order/Position Alignment)
  |
  v
Phase 4 (Order Book at Ingestion Boundary)
```

Each phase is strictly independent of later phases but provides the enum/mapping infrastructure they build on.

---

## Appendix A: Current vs. Target Architecture Comparison

| Concern | Current (PolySignal-managed) | Target (Nautilus-managed) |
|---|---|---|
| Data ingestion | `from_polymarket()` / `from_gamma()` | `PolymarketLiveDataClientFactory` |
| Order-book state | `OrderBook` Pydantic model | `OrderBookSnapshot` / `OrderBookDeltas` |
| Order lifecycle | `PaperOrder` + custom executor | Nautilus `Order` + sandbox execution |
| Position tracking | `PaperPosition` custom model | Nautilus `Position` + portfolio |
| Order status | Custom `OrderStatus` enum | `nautilus_trader.model.enums.OrderStatus` |
| Instrument ID | Ad-hoc string construction | `get_polymarket_instrument_id()` |
| Market view | `MarketViewAssembler` (stays) | Same (Polysignal-specific) |
| Signal / Alpha | Entirely custom (stays) | Same (Polysignal-specific) |

## Appendix B: File Inventory for Migration

| File | Phase | Change |
|---|---|---|
| `src/.../nautilus_bridge/enum_parser.py` | Phase 1 | CREATE |
| `src/.../nautilus_runtime/native_order.py` | Phase 1 | REFACTOR (use enum parser) |
| `src/.../nautilus_bridge/market_catalog.py` | Phase 2 | EXTEND (BinaryOption fields) |
| `src/.../nautilus_bridge/order_converter.py` | Phase 3 | CREATE |
| `src/.../nautilus_bridge/position_converter.py` | Phase 3 | CREATE |
| `src/.../domain/paper_order.py` | Phase 3 | DEPRECATE |
| `src/.../domain/paper_position.py` | Phase 3 | DEPRECATE |
| `src/.../domain/orderbook.py` | Phase 4 | STRIP |
| `src/.../nautilus_bridge/market_view_assembler.py` | Phase 4 | EXTEND (NautilusBookProvider) |
