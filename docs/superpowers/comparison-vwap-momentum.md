# VWAP Momentum Strategy: Reference vs Implementation Comparison

**Reference (correct):** `/home/gyue/polysignal-lab/refs/polymarket-arbitrage-bot/btc-binary-VWAP-Momentum-bot/main.py`  
**Our implementation:** `/home/gyue/polysignal-lab/src/polysignal_lab/strategies/vwap_momentum.py`  
**Base class:** `/home/gyue/polysignal-lab/src/polysignal_lab/strategies/base.py`  
**Config:** `/home/gyue/polysignal-lab/src/polysignal_lab/strategies/config.py` (lines 17-33)

Date: 2026-06-23

---

## 1. Momentum Calculation -- ALGORITHMIC MISMATCH

### Priority: HIGH

### What the reference does (correctly)

`IndicatorCalculator.calc_momentum()` at refs:main.py:224-246 uses a **time-band** approach:

```python
def calc_momentum(trades, current_price, window=120, avg_band=1.5):
    now = time.time()
    band_start = now - window - avg_band     # 121.5s ago
    band_end   = now - window + avg_band     # 118.5s ago
    band_prices = [t.price for t in trades if band_start <= t.timestamp <= band_end]
    if not band_prices:
        return None
    avg_price_ago = sum(band_prices) / len(band_prices)
    return ((current_price - avg_price_ago) / avg_price_ago) * 100  # PERCENTAGE
```

Key properties:
1. Looks back ~`window` seconds (default 120s) with a narrow +-1.5s band
2. Computes the **arithmetic mean** of all trades in that band
3. Returns **percentage** change from that mean to `current_price`
4. Returns `None` if no trades fell in that exact band (insufficient history)
5. Default window = 120s, band = 1.5s on each side (3s total)

### What our implementation does

`TradeHistory.momentum()` at vwap_momentum.py:54-62:

```python
def momentum(self, key, window_sec, now):
    trades = self.trades_in_window(key, window_sec, now)  # ALL trades in [now-window, now]
    if len(trades) < 2:
        return None
    p0 = trades[0].price    # oldest trade in window
    p1 = trades[-1].price   # newest trade in window
    return (p1 - p0) / p0   # FRACTIONAL
```

Key properties:
1. Takes **all** trades in `[now - window_sec, now]`
2. Uses **first and last trade prices** (no averaging)
3. Returns **fractional** change (not percentage)
4. Requires at least 2 trades in the entire window, which is a much weaker history requirement

### The problem

These are **completely different algorithms**:

| Aspect | Refs (correct) | Ours |
|--------|---------------|------|
| Reference point | Mean price in a 3s band ~window_sec ago | Price of oldest trade in the window |
| Window semantics | A narrow band at a specific past time | The entire window up to now |
| Tolerance for missing data | Returns None if no trade in the exact band | Always works if >=2 trades anywhere in window |
| Output unit | Percentage (0.05 = 5%) | Fractional (0.05 = 5%) |
| Default window | 120s (from refs dashboard "Mom 120s") | 60s (config: momentum_window_sec: 60) |

The refs approach is designed to measure "how much has the price moved from a specific point in the past" with precision. The time band (+-1.5s) ensures you're measuring from roughly the same moment, while the mean smooths noise. Our approach uses whatever is the oldest trade in the window, which could be anywhere from 1s to 60s old depending on trade arrival.

### What needs to change

1. **Rewrite `TradeHistory.momentum()` to use the time-band approach:**
   - Define `avg_band = 1.5` (matching refs)
   - Compute `band_start = now - window_sec - avg_band`
   - Compute `band_end = now - window_sec + avg_band`
   - Filter trades to those in `[band_start, band_end]`
   - Return `None` if no trades found
   - Compute mean price of the band
   - Return `(current_price - mean_price) / mean_price` (fractional, consistent with our other functions)

2. **Update the window default:** Change `momentum_window_sec` from 60 to 120 in `VWAPMomentumConfig` to match refs.

3. **Update the threshold:** Change `min_momentum` from 0.01 (1%) to 0.05 (5%) to match refs' `mom_ok = fav_mom is not None and fav_mom > 5` (which is >5% when expressed as percentage, i.e., >0.05 fractional).

---

## 2. Deviation Calculation -- CORRECT ALGORITHM, WRONG UPPER BOUND THRESHOLD

### Priority: HIGH

### What the reference does (correctly)

`IndicatorCalculator.calc_deviation()` at refs:main.py:218-221:

```python
def calc_deviation(current_price, vwap):
    if vwap == 0:
        return 0.0
    return ((current_price - vwap) / vwap) * 100  # PERCENTAGE
```

Returns **percentage** (e.g., 2.5 means 2.5% deviation). The entry check is:

```python
dev_ok = fav_dev > min_dev and fav_dev < max_dev  # fav_dev already in percent
```

From the refs startup log: `Dev 1.5%-5%` -> min_dev = 1.5 (percent), max_dev = 5 (percent).

### What our implementation does

`VWAPMomentumStrategy.evaluate()` at vwap_momentum.py:204:

```python
deviation_pct = (current_price - vwap) / vwap  # FRACTIONAL (named misleadingly)
```

Returns **fractional** (e.g., 0.025 means 2.5% deviation). The entry check is:

```python
if not (self.config.min_deviation_pct < deviation_pct < self.config.max_deviation_pct):
    return []
```

Config values: `min_deviation_pct = 0.015`, `max_deviation_pct = 1.0`

### Analysis

The algorithm is **self-consistent**: both the output and threshold are in the same units (fractional).

- `min_deviation_pct = 0.015` (fractional) = `1.5%` -- **matches** refs min_dev of 1.5
- `max_deviation_pct = 1.0` (fractional) = `100%` -- **does NOT match** refs max_dev of 5 (which is 5% = 0.05 fractional)

Setting max_deviation to 100% means the upper bound filter is **effectively disabled**. In binary options markets (where prices range from ~0.01 to ~0.99), a 100% deviation means the price would need to be at 2x VWAP, which is impossible. The max deviation check never rejects entries.

The refs use max_dev = 5% (0.05 fractional) to filter out trades that are too far from VWAP (indicating extreme momentum that is likely to revert).

### What needs to change

```python
# In VWAPMomentumConfig (config.py):
max_deviation_pct: float = 0.05  # was 1.0 -- corresponds to refs' 5%
```

---

## 3. Momentum Threshold -- 5x MORE RESTRICTIVE IN REFS

### Priority: HIGH

### Reference threshold

In the refs strategy panel (main.py:1082):
```python
mom_ok = fav_mom is not None and fav_mom > 5  # 5 PERCENT
```

The refs dashboard also shows "Mom 120s" confirming momentum_window_sec = 120s. The entry requires momentum > 5% (percentage).

### Our threshold

Config: `min_momentum = 0.01` (fractional, = 1%) and `momentum_window_sec = 60`.

### Analysis

| Aspect | Refs | Ours |
|--------|------|------|
| Threshold | > 5% (percentage) | > 0.01 (fractional, = 1%) |
| Window | 120s | 60s |

Even accounting for the different momentum algorithm, a 1% threshold with a 60s window is much easier to satisfy than a 5% threshold with a 120s window. This will cause our strategy to trigger many more false-positive signals.

However, the threshold value must be **re-evaluated after fixing the momentum algorithm** (see finding #1), since the algorithms produce different numerical values for the same data.

### What needs to change

After the momentum algorithm is fixed per finding #1:
1. Set `min_momentum = 0.05` (fractional 5%) in config
2. Set `momentum_window_sec = 120` in config
3. Calibrate in simulation -- the refs value of 5% was tuned for their specific time-band algorithm

---

## 4. Entry Conditions -- FULL FLOW COMPARISON

### Priority: MEDIUM

### Refs entry flow (main.py:1075-1116)

```python
price_ok = min_price <= fav_price <= max_price        # 1. Price range (fav_price = last_price)
time_ok = elapsed_sec >= min_elapsed                   # 2. Time elapsed
dev_ok = fav_dev > min_dev and fav_dev < max_dev      # 3. Deviation (percentage)
mom_ok = fav_mom is not None and fav_mom > 5          # 4. Momentum > 5%
time_cutoff_ok = time_left > no_entry_cutoff          # 5. Not too close to end
```

### Our entry flow (vwap_momentum.py:122-259)

```python
1.  Asset check
2.  Timeframe check
3.  Active market check
4.  Orderbook freshness check (max_orderbook_staleness_ms)    [NOT in refs]
5.  Spread check (max_spread)                                  [NOT in refs]
6.  Price range: min_price <= target_ask <= max_price          [Uses ASK, refs uses last_price]
7.  Time elapsed: elapsed_sec >= min_elapsed_sec
8.  Time cutoff: seconds_to_close > no_entry_before_end_sec
9.  VWAP calculation
10. Deviation check (min_deviation_pct < deviation < max_deviation_pct)
11. Momentum check (momentum > min_momentum)                   [Different threshold]
12. Z-score check (z_score >= min_z_score)                     [NOT in refs]
13. One-shot entry guard
```

### Key differences

| Check | Refs | Ours | Impact |
|-------|------|------|--------|
| Price source | `fav_price` = max(up.last_price, down.last_price) | `target_ask` = snapshot.ask_for(fav_side) | Ours uses ask (higher than last), making it harder to pass min_price |
| Favorite side | Higher `last_price` | Higher **ask** (`snapshot.favorite_side` at snapshot.py:84-87) | Could differ if spread asymmetry flips the ranking |
| Spread check | Not present | `max_spread: 0.03` | Additional safety filter -- fine to keep |
| Orderbook freshness | Not present | `max_orderbook_staleness_ms: 60000` | Additional safety filter -- fine to keep |
| Z-score filter | Not present (only displayed) | `min_z_score: 1.2` | Additional filter not in refs -- should be validated |
| Win rate table | Loaded from CSV, displayed in dashboard | Not present | Gap to note |
| Chainlink BTC price | Connected, displayed in dashboard | Not present | Gap to note |
| "ALMOST" signal tier | `fav_price >= 0.70` activates softer messaging | Not present | Low priority |

### What needs to change

1. **Align price source for range check:** Our `evaluate()` checks `target_ask` against `[min_price, max_price]`. The refs check `fav_price` (last_price of the side with higher last_price). These two values can differ by the spread. For strict alignment, check both the target_ask (execution price) AND the favorite-side last_price (signal price). Or at minimum, document the divergence.

2. **Z-score check:** The z-score filter at vwap_momentum.py:215-217 is an addition not present in refs. It should be reviewed: a z-score of 1.2 with a small window (vwap_window_sec=30) may not be meaningful. Either remove it or set min_z_score to 0.0 to disable until validated.

3. **Win rate table:** Consider adding a `WinRateTable`-like class that loads from a CSV and provides context. Not blocking since refs also only display it (not a strict gate).

Note: Items 4-5 (orderbook freshness, spread check) are reasonable safety checks that our platform-level architecture provides. They are an improvement over the refs, not a deficiency.

---

## 5. One-Shot Entry Guard -- DIFFERENT SEMANTICS

### Priority: HIGH

### Reference (main.py:363-378)

```python
class TradingStats:
    def new_market(self, slug):
        if slug != self.current_market_slug:
            self.current_market_slug = slug
            self.position = None
            self.position_closed_this_market = False   # reset for new market
            self.entry_blocked = False                  # reset for new market

    def can_enter(self) -> bool:
        return (self.position is None
                and not self.position_closed_this_market
                and not self.entry_blocked)
```

Behavior:
- On `close_position()` -> `position_closed_this_market = True` (blocks re-entry on same market)
- On `new_market(slug)` -> resets both flags (re-entry allowed on NEXT market)
- Also has `entry_blocked` for timeout-based blocking

### Ours (vwap_momentum.py:105, 219-222)

```python
self._can_enter: dict[str, bool] = defaultdict(lambda: True)

# In evaluate():
if not self._can_enter[snapshot.market.market_id]:
    return []
self._can_enter[snapshot.market.market_id] = False
```

Behavior:
- On first entry for a `market_id` -> set to False
- **NEVER** reset -- permanently blocks that `market_id` forever
- Re-entry on the same market_id is impossible even across evaluations

### Problem

The refs guard is **session-scoped** and resets per market. Our guard is **permanent** for a market_id. If the same market_id appears in a later snapshot (e.g., the strategy is re-evaluated after position close), our code will never emit a signal again.

In practice:
- Markets with different IDs work fine in both
- **Ours deadlocks** if the same market_id receives multiple evaluations across different lifecycle phases

### What needs to change

Option A (match refs): Add position-closed tracking with lifecycle reset.
Option B (simpler, for signal-only mode): Document current behavior as intentional.

**Recommended:** Option B for now (the guard is acceptable for signal-only mode). Implement Option A if position tracking is added.

---

## 6. Confidence Calculation -- NOT IN REFS

### Priority: LOW

### Our implementation (vwap_momentum.py:265-270)

```python
@staticmethod
def _compute_confidence(deviation_pct: float, momentum_pct: float) -> float:
    base = 0.50
    dev_contrib = max(0.0, min(0.25, abs(deviation_pct) * 2.0))
    mom_contrib = max(0.0, min(0.20, momentum_pct * 3.0))
    return min(0.95, base + dev_contrib + mom_contrib)
```

### Reference

The refs does not have a confidence function. Signal generation is binary -- either all conditions are met or not.

### Analysis

For a typical entry with deviation=0.02 (2%) and momentum=0.02 (2%):
- `dev_contrib = min(0.25, 0.04) = 0.04`
- `mom_contrib = min(0.20, 0.06) = 0.06`
- Total: `0.50 + 0.04 + 0.06 = 0.60`

This is reasonable. However, note the variable name confusion: `momentum_pct` is actually a **fractional** value. If the momentum algorithm is fixed per finding #1, the output will change numerically and the multipliers (2.0x, 3.0x) may need retuning.

### What needs to change

1. Rename `momentum_pct` to `momentum_frac` to avoid confusion
2. After fixing the momentum algorithm, validate the formula produces reasonable values (0.55-0.75 for typical entries)

---

## 7. Missing Features (Platform-Level Differences)

### Priority: LOW (by design for signal-only mode)

| Feature | Refs | Ours | Notes |
|---------|------|------|-------|
| Hedge management | `HedgeManager` places GTD orders | Not present | Platform handles via paper trading |
| Chainlink BTC price | RTDS WebSocket, anchor tracking | Not present | Not relevant for signal-only |
| Auto-redeemer | On-chain redemption | Not present | Not relevant for signal-only |
| Win rate table | CSV-loaded, displayed | Not present | Nice-to-have |
| Order execution | Live CLOB, fill recovery | Paper trading model | Different by design |

These are not bugs -- they reflect the different purpose of our system. No changes needed unless live execution is added.

---

## Summary of Required Changes

### HIGH priority (will cause incorrect signals)

| # | Issue | File(s) | Change |
|---|-------|---------|--------|
| 1 | Momentum algorithm: first/last trade vs time-band mean | `vwap_momentum.py` `TradeHistory.momentum()` | Rewrite to refs' time-band (+-1.5s) arithmetic-mean approach |
| 1b | Momentum window too short (60s vs 120s) | `config.py` `momentum_window_sec` | Change to `120` |
| 1c | Momentum threshold too low (0.01 = 1% vs 5%) | `config.py` `min_momentum` | Change to `0.05` (AFTER fixing algorithm) |
| 2 | Max deviation threshold = 100% (disabled) vs refs 5% | `config.py` `max_deviation_pct` | Change to `0.05` |
| 3 | One-shot guard never resets | `vwap_momentum.py` `_can_enter` | Document as intentional for signal-only mode |
| 4 | Z-score filter not in refs, may gate valid entries | `vwap_momentum.py` evaluate() | Review and reduce/remove if not validated |

### MEDIUM priority (correctness edge cases)

| # | Issue | File(s) | Change |
|---|-------|---------|--------|
| 5 | Price range check uses ask vs refs' last_price | `vwap_momentum.py` evaluate() | Align or document divergence |
| 6 | Favorite side determined by ask vs refs' last_price | `snapshot.py` favorite_side() | Align or document divergence |
| 7 | Momentum returns fractional not percentage | `vwap_momentum.py` | Document consistent with system design |

### LOW priority (enhancements)

| # | Issue | File(s) | Change |
|---|-------|---------|--------|
| 8 | Confidence param named `momentum_pct` but is fractional | `vwap_momentum.py` | Rename to `momentum_frac` |
| 9 | Win rate table not present | -- | Add as nice-to-have metadata |
| 10 | Chainlink BTC context not present | -- | Not relevant for signal-only mode |

---

## Algorithm Trace: Correct Momentum Calculation

Here is the precise pseudo-code for the corrected `TradeHistory.momentum()` matching the refs:

```python
def momentum(self, key: str, window_sec: float, now: float) -> float | None:
    trades = self._trades.get(key, [])
    band_width = 1.5  # seconds on each side (matching refs)
    band_start = now - window_sec - band_width
    band_end = now - window_sec + band_width

    band_prices = []
    for t in trades:
        if band_start <= t.timestamp <= band_end:
            band_prices.append(t.price)

    if not band_prices:
        return None  # No trades in the band -- not enough history

    mean_price = sum(band_prices) / len(band_prices)
    if mean_price <= 0:
        return None

    current_price = self.latest_price(key)
    if current_price is None or current_price <= 0:
        return None

    return (current_price - mean_price) / mean_price  # fractional, consistent with system
```

The existing `trades_in_window()` cannot be reused because it returns `[now-window, now]` trades, and we need trades specifically around `now - window`.
