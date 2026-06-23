# PTB Diff Strategy: Reference vs Implementation Comparison

**Date:** 2026-06-23
**Reference:** `refs/polymarket-arbitrage-bot/5min-15min-PTB-bot/polymarket_auto_trade.py`
**Ours:** `src/polysignal_lab/strategies/ptb_diff.py`
**Config:** `src/polysignal_lab/strategies/config.py` (PTBDiffConfig, PTBTriggerConfig, PTBExitConfig)
**Base class:** `src/polysignal_lab/strategies/base.py`

---

## 1. DIFF CALCULATION: PRICE SOURCE

### Reference (correct)
```
diff = btc - ptb
```
Where:
- `btc` = Chainlink BTC/USD price from Polymarket RTDS WebSocket (`crypto_prices_chainlink` topic)
- `ptb` = Price-to-Beat from Polymarket crypto-price API (`get_crypto_price_api`)
- Binance BTC price is maintained as a secondary/fallback reference but NEVER used for diff calculation

### Ours
```
diff = snapshot.spot.price - snapshot.price_to_beat
```
Where:
- `snapshot.spot.price` = Binance BTC/USDT spot price (from `binance_spot_ws`)
- `snapshot.price_to_beat` = Price-to-Beat from Polymarket (gamma / crypto-price API)

### Analysis
**CRITICAL DIFFERENCE.** Polymarket BTC up/down markets settle based on the **Chainlink BTC/USD oracle**, not Binance BTC/USDT. There is a known spread between Binance and Chainlink prices (often $10-$50 during normal conditions, wider during volatility). Using Binance instead of Chainlink means:

- The diff magnitude is systematically different from what the reference uses
- The diff can have the **wrong sign** if Binance and Chainlink diverge, causing false positives or false negatives
- Chainlink aggregates multiple exchange prices and is the settlement oracle; Binance is just one exchange

**PRIORITY: HIGH**

**Fix:**
1. Integrate Chainlink BTC/USD price feed into the data pipeline (`polymarket_clob_rest.py` or `polymarket_market_discovery.py` already fetches crypto-price data)
2. Add a `chainlink_btc` field to `MarketSnapshot` or `SpotPrice` with source `"chainlink"`
3. In `PTBDiffStrategy.evaluate()`, use `snapshot.metrics.get("chainlink_btc")` instead of `snapshot.spot.price` for the diff calculation
4. Keep Binance price as a fallback only if Chainlink is unavailable

---

## 2. TRIGGER RULES CONCEPTUAL MODEL

### Reference
4 hardcoded rules with fixed parameters:
```
R1: remaining <= 120s, diff >= +$30,  UP, prob [0.80, 0.92]
R2: remaining <= 120s, diff <= -$30, DOWN, prob [0.80, 0.92]
R3: remaining <= 60s,  diff >= +$50,  UP,  prob [0.80, 0.92]
R4: remaining <= 60s,  diff <= -$50, DOWN, prob [0.80, 0.92]
```
The rules form a **priority ladder** -- R1 is checked first, then R2, R3, R4, in order. Only one can fire per loop iteration (the `elif` chain).

### Ours
Configurable triggers via `PTBTriggerConfig`:
```python
PTBTriggerConfig(
    name="strong_up_late",
    side=Side.UP,
    min_diff_usd=80.0,
    max_token_price=0.85,
    min_probability_edge=0.08,
    min_seconds_to_close=30,
    max_seconds_to_close=180,
)
```
Default triggers iterate independently (for loop). Each trigger can fire independently, but the first match returns.

### Analysis
**MODERATE DIFFERENCE.** Ours is more flexible (configurable per-trigger parameters). However:

1. The **default values differ significantly** from the refs: refs R1 uses diff >= $30 and 120s max; our default uses min_diff_usd=80 and max_seconds_to_close=180. This means our defaults are **less sensitive** (higher diff threshold) but **wider time window**.

2. The reference cascades rules (R1->R2->R3->R4 with `elif`), meaning higher-diff rules apply in the final minute. Our triggers are independent candidates.

3. Both approaches work, but the reference's specific parameters were empirically tuned. Ours should replicate at least a superset.

**PRIORITY: MEDIUM**

**Fix:**
- Add default triggers that match all 4 reference rules (120s/30-diff UP, 120s/30-diff DOWN, 60s/50-diff UP, 60s/50-diff DOWN)
- Ensure the parameter units match (refs uses `remaining <= C1_TIME`, i.e. max_seconds_to_close = 120)

---

## 3. PROBABILITY EDGE CHECK -- CRITICAL MISMATCH

### Reference
```python
prob = up_entry_price  # aka the ASK price for the UP token
if C1_MIN_PROB <= prob <= C1_MAX_PROB:  # [0.80, 0.92]
    triggered = True  # R1 -- UP triggered
```
The probability check is a **direct range check on the token ask price**. The token price IS the probability.
- `0.80 <= ask_price <= 0.92` means the market prices the outcome at 80%--92%
- The lower bound (0.80) filters out situations where the market disagrees too much with the diff signal
- The upper bound (0.92) filters out situations where the token is too expensive (no profit left)

### Ours
```python
directional_probability = 1.0 if diff_usd > 0 else 0.0  # (for UP side)
probability_edge = max(0.0, directional_probability - entry_price)
```
The check is: `probability_edge >= trigger.min_probability_edge`

This is **fundamentally different** from the reference's approach:
1. `directional_probability` is always 1.0 or 0.0 -- a crude binary that asserts 100% certainty that the direction is correct
2. `probability_edge = 1.0 - entry_price` when diff supports the side
3. `probability_edge >= 0.08` is equivalent to `entry_price <= 0.92`

### Mathematical divergence

| Check | Refs eq | Ours eq |
|-------|---------|---------|
| Upper bound | `ask <= 0.92` | `ask <= 0.92` (via edge >= 0.08) |
| Lower bound | `ask >= 0.80` | **NONE** |
| Semantics | Market prices outcome at 80-92% -- good entry | Market thinks outcome has `ask` prob; we think 100% so "edge" is `1-ask` |

**Our approach has no lower bound equivalent.** If the market prices UP at 0.50 (50%), our method computes:
- directional_probability = 1.0 (diff > 0)
- probability_edge = 1.0 - 0.50 = 0.50 >= 0.08 -> **PASS**

The reference would check: `0.80 <= 0.50 <= 0.92` -> **FAIL** (would skip because prob is too low)

This means our implementation will **enter positions the reference would reject** -- specifically, entries where the token price is below 80%. These are lower-confidence entries where the market strongly disagrees with the diff signal.

Additionally, the reference checks the **opposite side token** implicitly: if UP entry is being considered, the UP price in 80-92% range means DOWN price is 8-20%, which is consistent with a strong directional bet. Our method doesn't validate this.

**PRIORITY: HIGH**

**Fix:**
1. Remove the `_directional_probability()` method that returns binary 0/1
2. Replace with a **direct range check** matching the reference: `trigger.min_token_price <= entry_price <= trigger.max_token_price`
3. Add `min_token_price` field to `PTBTriggerConfig` (default 0.80 to match refs)
4. The `probability_edge` concept should be removed or redefined as the distance between token ask and the nearest boundary of the acceptable range
5. Alternatively, keep edge as a secondary filter but ensure the primary check is the range gate

---

## 4. TP/SL CALCULATION

### Reference
```python
stop_prob = max(0.0, entry_prob * (1.0 - STOP_LOSS_PROB_PCT))    # default: entry * 0.85
risk_abs = max(0.0, entry_prob - stop_prob)                       # default: entry * 0.15
tp_trigger = min(TAKE_PROFIT_CAP, entry_prob + risk_abs * TAKE_PROFIT_RR)  # cap at 0.99
if tp_trigger <= entry_prob:
    tp_trigger = None
# Rebalance if capped:
balanced_risk = (tp_trigger - entry_prob) / TAKE_PROFIT_RR
balanced_stop = max(0.0, entry_prob - balanced_risk)
if balanced_stop > stop_prob:
    stop_prob = balanced_stop
```
Parameters: `SL=0.15`, `RR=1.0`, `CAP=0.99`

### Ours
```python
def compute_tp_sl_thresholds(entry_prob, stop_loss_pct, tp_rr, tp_cap): ...
```
**Algorithm is mathematically identical.** Same calculation steps, same rebalancing when capped.

### Default parameter divergence

| Parameter | Refs | Ours | Impact |
|-----------|------|------|--------|
| STOP_LOSS_PROB_PCT | 0.15 (15%) | 0.20 (20%) | SL triggers earlier (looser stop) |
| TAKE_PROFIT_RR | 1.0 | 3.0 | TP target is much more aggressive |
| TAKE_PROFIT_CAP | 0.99 | 0.95 | Lower cap on TP |

Example with entry at 0.85:
- **Refs:** SL = 0.7225, risk = 0.1275, TP = 0.9775 (capped at 0.99 -> 0.9775)
- **Ours:** SL = 0.68, risk = 0.17, TP = min(0.95, 0.85+0.17*3) = min(0.95, 1.36) = 0.95

With RR=3.0, the TP immediately hits the cap of 0.95 for most entries above ~0.82. The rebalancing then tightens the stop:
- Capped TP = 0.95, balanced_risk = (0.95-0.85)/3.0 = 0.0333, balanced_stop = 0.8167
- Since 0.8167 > 0.68, stop_prob becomes 0.8167

So the effective stop is **much tighter** (0.8167 vs refs 0.7225). This means positions will be stopped out much sooner -- a 4% drop from entry triggers SL vs refs 15%.

**PRIORITY: HIGH**

**Fix:**
- Align default parameters with the reference: `stop_loss_prob_pct=0.15`, `take_profit_rr=1.0`, `take_profit_cap=0.99`
- Or document that these are intentionally different and provide justification

---

## 5. FRESHNESS / STALE DATA CHECKS

### Reference
```python
side_age = now - side_ts if side_ts > 0 else 999.0
btc_age = now - btc_ts if btc_ts > 0 else 999.0
if side_age > MARKET_DATA_MAX_LAG_SEC or btc_age > MARKET_DATA_MAX_LAG_SEC:
    triggered = False  # skip
```
Default: `MARKET_DATA_MAX_LAG_SEC = 1.2s`
- Checks both orderbook age and BTC price age independently
- Uses actual timestamps from the WebSocket data

### Ours
```python
orderbook_freshness_ms = side_book.freshness_ms(now)  # received_at based
spot_freshness_ms = snapshot.spot.freshness_ms(now)
if orderbook_freshness_ms > max_lag_ms: continue
if spot_freshness_ms > max_lag_ms: continue
```
Default: `market_data_max_lag_sec = 2` (in `PTBExitConfig`)
- Checks both orderbook and spot freshness
- Uses `received_at` timestamps (when the data was received by our system)

### Analysis
**MINOR DIFFERENCE.** Conceptually the same check. Our default is looser (2s vs 1.2s). Our freshness is based on when we received the data, not on the exchange's source timestamp. This could be slightly less accurate during network congestion but is functionally equivalent.

**PRIORITY: LOW**

**Fix:**
- Tighten default to match refs: `market_data_max_lag_sec = 1.2`
- Consider using source timestamps instead of received_at for more accuracy
- Add stale data logging (refs logs `"Stale data skip"` every 2 seconds, ours silently skips)

---

## 6. RETRY / CHASE LOGIC

### Reference
```python
if same_key_retry and retry_count > 0:
    last_price = last_order.get("last_price", price)
    retry_cap_price = min(0.995, last_price + BUY_RETRY_STEP)  # step = 0.01 (1%)
    price = min(price, retry_cap_price)  # Cap chase to step above last attempt
```
- Up to `MAX_RETRY_PER_MARKET = 2` attempts per (slug, side) pair
- Each retry caps the entry price at `last_price + 1%` (prevents chasing too aggressively)
- Retry state persisted in `state.json` via `last_order["retry_count"]` and `last_order["last_price"]`

### Ours
**NOT PRESENT.** The strategy generates a single signal candidate per trigger match. There is no retry/chase mechanism. The paper simulator (`PaperSimulator.process_signal()`) is one-shot: it either fills or rejects.

### Analysis
**MAJOR MISSING FEATURE.** The reference's retry logic is important because:
1. Limit orders may not fill immediately, especially in fast-moving markets
2. The chase step allows re-entering at a slightly worse price rather than missing the opportunity entirely
3. The retry cap prevents "chasing" far above the original price

However, the retry logic in the refs is part of the main loop's order lifecycle management, which is a different architectural concern. Our system separates signal generation (strategy) from order execution (paper simulator / live trader). The retry logic would need to live in the execution layer.

**PRIORITY: MEDIUM**

**Fix:**
- Add retry parameters to `PTBExitConfig` (`max_retry_per_market`, `chase_step`)
- In the paper trading exit model or a new order manager layer, implement retry logic: when a signal fails to fill, re-evaluate the same trigger with a price cap
- Alternatively, the strategy itself could emit multiple signal candidates at different price levels (ladder approach)

---

## 7. SLIPPAGE THRESHOLD

### Reference
```python
slippage = abs(current_price - price) / price
if slippage > SLIPPAGE_THRESHOLD:  # 5%
    skip  # skip trade
```

### Ours
**NOT PRESENT in strategy.** The fill model has `slippage_bps = 25.0` (0.25%), but this is applied differently -- it adds 25bps to the reference price as the max acceptable price, rather than checking percentage deviation from the trigger price.

### Analysis
**MODERATE DIFFERENCE.** The refs check is: "at the moment we want to trade, has the price moved more than 5% since the trigger fired?" Ours doesn't have this check, meaning if the price moves significantly between snapshot evaluation and fill attempt, the order is still placed.

**PRIORITY: LOW** (the 25bps slippage in fill model provides some protection)

**Fix:**
- Add a configurable `slippage_threshold` to `PTBExitConfig`
- In the strategy (or execution layer), compare the current ask price against the trigger price and reject if exceeded

---

## 8. ORDER TIMEOUT / CANCEL

### Reference
```python
if elapsed > ORDER_TIMEOUT_SEC:  # 8s
    order_status = trader.get_order_status(order_id)
    if not filled: cancel_order(order_id)  # cancel and retry
```
- Full lifecycle management: submit -> poll -> cancel on timeout -> retry

### Ours
**NOT PRESENT.** Signals are ephemeral. No order lifecycle management exists in the strategy or paper simulator.

### Analysis
**MISSING FEATURE.** This belongs in the execution layer rather than the strategy, but it's a critical component of a production system. Without it, orders that don't fill within 8 seconds would hang indefinitely.

**PRIORITY: MEDIUM**

**Fix:**
- Add order timeout handling to the execution/simulation layer
- Parameter: `order_timeout_sec: int = 8` in `ExitConfig`

---

## 9. ENTRY PRICE (ASK SIDE SELECTION)

### Reference
```python
up_entry_price = up_ask if (up_ask is not None and up_ask > 0) else up_price
```
Uses ask if available, falls back to mid price.

### Ours
```python
entry_price = snapshot.ask_for(wanted_side)
```
Which returns `book.best_ask`. No fallback to mid price.

### Analysis
**MINOR DIFFERENCE.** Ours is stricter -- always uses ask, never falls back to mid. This is actually better (more accurate entry price). The refs fallback was a safety measure for cases where the orderbook snapshot hadn't arrived yet. Our data pipeline should always have orderbook data by the time a snapshot is created.

**PRIORITY: LOW**

**Fix:** No change needed, but ensure orderbook is always populated for evaluated snapshots.

---

## 10. EXIT ARCHITECTURE -- TP/SL MONITORING

### Reference
**Monolithic loop** -- same loop that checks entry conditions also monitors positions:
```python
# In the main loop, after entry logic:
state = load_state()
pos = state.get("position")
if pos and pos["slug"] == slug:
    current_prob = up_price if pos_side == "UP" else down_price
    
    # Check stop-loss: current_prob <= stop_prob
    # Check take-profit: current_prob >= tp_trigger_prob
    
    # For SIMULATION_MODE: instant exit with calculation
    # For LIVE: place sell limit order, monitor fill
```
Continuous monitoring of position against dynamically calculated TP/SL levels. The TP/SL levels are recalculated each loop iteration from the entry price.

### Ours
**Strategy delegates exit** to the paper trading system:
```python
# PaperSettlementEngine.settle():
#   Exit only at resolution (no continuous TP/SL)
#   OR via ExitModelConfig with fixed prices:
#     take_profit_price = 0.90 (not entry-relative!)
#     stop_loss_price = 0.35  (not entry-relative!)
```

### Key differences:
1. **Dynamic vs fixed TP/SL**: Refs TP/SL is proportional to entry price (e.g., entry at 0.85 -> SL at 0.7225). Ours uses absolute values (SL at 0.35 regardless of entry) -- these are wildly different.
2. **Continuous vs point-in-time**: Refs monitors price continuously throughout the window. Ours only checks exit at market resolution (or when a new snapshot triggers evaluation).
3. **Same-side vs opposite-side**: Refs monitors the SAME token's price (if you bought UP, watch UP price for SL/TP). Ours doesn't have intra-window exit monitoring at all.

**PRIORITY: HIGH** -- this is the most architecturally significant difference. Without continuous position monitoring, the strategy can't implement prob-based TP/SL.

**Fix (architectural):**
1. Add a continuous position monitoring loop (separate from the strategy loop)
2. For each open position, periodically check the token's current ask/bid price against dynamic TP/SL levels
3. TP/SL levels should be stored at position open time (computed from entry_price using the same formula)
4. Add `PTBExitConfig` parameters that match the refs: `stop_loss_prob_pct: float = 0.15`, `take_profit_rr: float = 1.0`, `take_profit_cap: float = 0.99`

---

## 11. CONFIDENCE SCORE

### Reference
No confidence score. Binary trigger: either rules fire or they don't.

### Ours
```python
confidence = min(0.98, 0.55 + min(0.25, abs(diff) / 500) + min(0.18, probability_edge))
```
Computes a continuous confidence score incorporating:
- Base: 0.55
- Diff component: min(0.25, abs(diff)/500), giving +0.25 at diff=$125
- Edge component: min(0.18, probability_edge), giving +0.18 at 18% edge

### Analysis
**ADDED FEATURE** (not present in refs, not a bug). This is useful for downstream consumers (signal filtering, consensus across strategies) and is not a correctness concern. However, if the probability_edge calculation is changed (see #3 above), this confidence formula will need adjustment.

**PRIORITY: LOW** (informational)

---

## 12. SUMMARY OF ALL DIFFERENCES

| # | Item | Priority | Type | Fix Scope |
|---|------|----------|------|-----------|
| 1 | Diff price source: Binance vs Chainlink | **HIGH** | Bug | Data pipeline + strategy |
| 2 | Trigger rule default params drift | MEDIUM | Param | Config defaults |
| 3 | Probability edge: range check vs binary edge | **HIGH** | Bug | Strategy logic |
| 4 | TP/SL default parameters (SL=0.20 vs 0.15, RR=3 vs 1) | **HIGH** | Param | Config defaults |
| 5 | Stale data check timing | LOW | Param | Config defaults |
| 6 | Retry/chase logic missing | MEDIUM | Feature | Execution layer |
| 7 | Slippage threshold missing | LOW | Feature | Strategy/execution |
| 8 | Order timeout/cancel missing | MEDIUM | Feature | Execution layer |
| 9 | Entry price ask-side selection | LOW | Cosmetic | No change needed |
| 10 | Exit architecture: no continuous TP/SL monitoring | **HIGH** | Architecture | New system component |
| 11 | Confidence score added | LOW | Feature | No change needed |

---

## 13. RECOMMENDED ACTION PLAN

### Phase 1 (Critical -- fix bugs first)
1. **Fix probability check** (item #3): Replace binary directional_probability with range check `min_token_price <= entry_price <= max_token_price`
2. **Add Chainlink BTC reference** (item #1): Integrate Chainlink BTC/USD oracle price into the pipeline for diff calculation
3. **Fix TP/SL parameters** (item #4): Set `stop_loss_prob_pct=0.15`, `take_profit_rr=1.0`, `take_profit_cap=0.99`

### Phase 2 (Architecture)
4. **Implement continuous position monitoring** (item #10): Add a component that monitors open positions against prob-based TP/SL levels

### Phase 3 (Feature parity)
5. **Add retry/chase logic** (item #6): Implement in execution layer
6. **Add order timeout** (item #8): Implement in execution layer
7. **Align trigger defaults** (item #2): Add reference-equivalent default triggers
8. **Tighten stale data check** (item #5): Set `market_data_max_lag_sec=1.2`
9. **Add slippage check** (item #7): Compare current ask vs trigger price at execution time

---

## 14. CONCRETE CODE CHANGES

### 14a. PTBTriggerConfig -- add min_token_price

```python
# In strategies/config.py
class PTBTriggerConfig(BaseModel):
    name: str
    side: Side
    min_diff_usd: float
    max_token_price: float
    min_token_price: float = 0.80  # NEW: lower bound matching refs C1_MIN_PROB
    min_probability_edge: float = 0.08  # Can keep as secondary filter
    min_seconds_to_close: int
    max_seconds_to_close: int
```

### 14b. PTBDiffStrategy.evaluate() -- fix probability check

```python
# In ptb_diff.py evaluate() method, replace the probability_edge section:
# OLD:
directional_probability = self._directional_probability(diff, wanted_side)
probability_edge = max(0.0, directional_probability - entry_price)
if probability_edge < trigger.min_probability_edge:
    continue

# NEW (range check matching refs):
if not (trigger.min_token_price <= entry_price <= trigger.max_token_price):
    continue
# Optional secondary edge filter:
if trigger.min_probability_edge > 0:
    # Edge = how far from the boundary (0 = at boundary, positive = inside range)
    if entry_price < trigger.max_token_price:
        probability_edge = trigger.max_token_price - entry_price
    else:
        probability_edge = 0.0
    if probability_edge < trigger.min_probability_edge:
        continue
```

### 14c. PTBExitConfig -- align defaults with refs

```python
class PTBExitConfig(BaseModel):
    stop_loss_prob_pct: float = 0.15   # was 0.20
    take_profit_rr: float = 1.0         # was 3.0
    take_profit_cap: float = 0.99       # was 0.95
    market_data_max_lag_sec: int = 1    # was 2 (1.2s is hard to map, 1s is conservative)
```

### 14d. Default triggers -- match reference rules

```python
class PTBDiffConfig(BaseModel):
    # ...
    triggers: list[PTBTriggerConfig] = Field(default_factory=lambda: [
        # R1 equivalent: 120s, diff>=30, UP, 80-92%
        PTBTriggerConfig(
            name="R1_up_120s_30diff",
            side=Side.UP, min_diff_usd=30.0,
            max_token_price=0.92, min_token_price=0.80,
            min_probability_edge=0.0,
            min_seconds_to_close=0, max_seconds_to_close=120,
        ),
        # R2 equivalent: 120s, diff<=-30, DOWN, 80-92%
        PTBTriggerConfig(
            name="R2_down_120s_30diff",
            side=Side.DOWN, min_diff_usd=30.0,
            max_token_price=0.92, min_token_price=0.80,
            min_probability_edge=0.0,
            min_seconds_to_close=0, max_seconds_to_close=120,
        ),
        # R3 equivalent: 60s, diff>=50, UP, 80-92%
        PTBTriggerConfig(
            name="R3_up_60s_50diff",
            side=Side.UP, min_diff_usd=50.0,
            max_token_price=0.92, min_token_price=0.80,
            min_probability_edge=0.0,
            min_seconds_to_close=0, max_seconds_to_close=60,
        ),
        # R4 equivalent: 60s, diff<=-50, DOWN, 80-92%
        PTBTriggerConfig(
            name="R4_down_60s_50diff",
            side=Side.DOWN, min_diff_usd=50.0,
            max_token_price=0.92, min_token_price=0.80,
            min_probability_edge=0.0,
            min_seconds_to_close=0, max_seconds_to_close=60,
        ),
    ])
```

Note: The reference uses `elif` cascading (only one rule fires per loop). Our independent triggers mean multiple could match, but returning the first match preserves single-trigger behavior. To exactly match refs priority ordering, the triggers list must be ordered R1, R2, R3, R4.

### 14e. Confidence score update (after probability fix)

If the probability check is changed to a range gate, the confidence formula should reference the entry_price position within the range rather than the binary edge:

```python
# Instead of using probability_edge (which becomes a secondary filter):
price_position = 1.0 - (entry_price - trigger.min_token_price) / (trigger.max_token_price - trigger.min_token_price)
# 1.0 = at min boundary (cheapest), 0.0 = at max boundary (most expensive)
confidence = min(0.98, 0.55 + min(0.25, abs(diff) / 500) + max(0.0, 0.12 * price_position))
```
