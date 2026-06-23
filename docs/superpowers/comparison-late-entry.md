# Late Entry Strategy: Reference vs. PolySignal Lab Implementation

**Date:** 2026-06-23
**Reference:** `refs/polymarket-arbitrage-bot/up-down-spread-bot/src/strategy.py`
**Ours:** `src/polysignal_lab/strategies/late_consensus.py`

---

## Summary of Findings

| # | Area | Priority | Status |
|---|------|----------|--------|
| 1 | Time window scaling for 5m markets | **HIGH** | BUG |
| 2 | Position sizing thresholds (5m vs 15m) | **HIGH** | BUG |
| 3 | Flip-stop vs. flip-guard (conceptual mismatch) | **HIGH** | BUG |
| 4 | Spot move as additional entry gate (not in refs) | **HIGH** | EXTRA |
| 5 | Max_investment_per_market not enforced in strategy | **MEDIUM** | MISMATCH |
| 6 | Extra orderbook spread check (not in refs) | **MEDIUM** | EXTRA |
| 7 | Hedge signal omitted from output | **LOW** | MISSING |
| 8 | Entry frequency (trivially different) | **LOW** | OK |
| 9 | Price ceiling default mismatch | **LOW** | OK |
| 10 | Stop-loss price differs (0.35 vs 0.48) | **HIGH** | MISMATCH |

---

## 1. Time Window (Step 1) -- HIGH

### Reference (`strategy.py`, lines 21-26)
```python
default_entry = 240 if self.market_interval_sec >= 900 else min(120, self.market_interval_sec - 10)
raw_ew = int(strategy_cfg.get("entry_window_sec", default_entry))
# Smart override detection: if on 5m and config still has 240, use default_entry
if self.market_interval_sec < 900 and raw_ew > self.market_interval_sec * 0.5:
    raw_ew = default_entry
self.entry_window = min(raw_ew, max(10, self.market_interval_sec - 5))
```

**Key behaviors:**
- **15m market** (900s): default_entry = 240s
- **5m market** (300s): default_entry = min(120, 300-10) = 120s
- Smart guard: if config still says 240 but we're on 5m, override to 120s
- Absolute cap: at most `market_interval_sec - 5` (295s for 15m, 295s for 5m)
- Minimum floor: 10s

### Ours (`late_consensus.py`, lines 66-69)
```python
if seconds > self.config.entry_window_sec:
    return []
```
With `entry_window_sec` defaulting to `240` in `LateConsensusConfig` (config.py, line 52).

**No market-adaptive scaling.** If configured as 240 and running on 5m markets, the bot waits 240s when the market is only 300s long. On 5m, it starts entering at 60s after market open (300-240=60). Refs starts at 180s after market open (300-120=180). The refs behavior is deliberate: wait longer before committing on short markets.

**Fix needed:**
```python
# In evaluate(), compute scaled window:
market_interval_sec = 900  # or derive from snapshot/trade config
default_window = 240 if market_interval_sec >= 900 else min(120, market_interval_sec - 10)
effective_window = min(self.config.entry_window_sec, max(10, market_interval_sec - 5))
# If config value looks like a 15m value on a 5m market, override
if market_interval_sec < 900 and self.config.entry_window_sec > market_interval_sec * 0.5:
    effective_window = default_window
```

---

## 2. Entry Frequency (Step 2) -- LOW

**Refs:** Tracks last entry per market via `time.time()`, blocks if `< 7s` since last entry.

**Ours:** Same concept via `utc_now()` and `_last_entry_at` dict.

**Difference:** `utc_now()` returns `datetime.utcnow()` (wall clock) vs. `time.time()` (epoch seconds). Both are monotonic within a single process; the comparison is correct in both cases.

**Status:** Functionally identical. No fix needed.

---

## 3. Spread Check (Step 3) -- MEDIUM (EXTRA CHECK EXISTS)

### Reference (`strategy.py`, lines 83-86)
```python
spread = up_ask + down_ask
if spread > self.max_spread or spread <= 0:
    return None
```
One check: `up_ask + down_ask <= 1.05`.

### Ours (`late_consensus.py`, lines 79-81 AND 96-98)
**Check A** (line 79-81):
```python
max_spread = snapshot.max_spread
if max_spread is None or max_spread > self.config.max_spread:
    return []
```
This checks `max(orderbook.up.spread, orderbook.down.spread)` where spread = `(best_ask - best_bid) / best_ask` (the orderbook's bid-ask spread, a small value typically <0.08). Config default: `max_spread = 0.08`.

**Check B** (line 96-98):
```python
ask_sum = up_ask + down_ask
if ask_sum <= 0 or ask_sum > self.config.max_ask_sum:
    return []
```
This checks `up_ask + down_ask <= 1.05`, same as refs.

**Problem:** Check A (`max_spread > 0.08`) is an **additional constraint** not present in the reference. This filter rejects entries where either side's orderbook is too wide (low liquidity). This is a valid quality filter but means our implementation will skip entries the reference would take. The reference only checks the sum of ask prices (~1.05), not the bid-ask spread of individual books.

**Also:** The reference calls this `max_spread = 1.05` (sum of asks), while our `max_spread = 0.08` (bid-ask spread). **Naming collision here is dangerous** -- they are different concepts with the same name.

**Fix needed:**
- Rename `max_spread` in our config to something like `max_book_spread` to avoid confusion with the refs' `max_spread` (which is sum of asks).
- Decide whether the extra book-spread check is desired (keep as additional quality gate, or remove to match refs).

---

## 4. Confidence Check (Step 4) -- OK

Both use `abs(up_ask - down_ask) >= 0.30`.

**Refs:** `min_confidence = 0.30` from config key `min_confidence`.

**Ours:** `min_confidence_abs = 0.30` via `min_confidence or min_confidence_abs`.

**Status:** Functionally identical. The dual-field lookup is a detail that doesn't affect behavior.

---

## 5. Identify Favorite Side (Step 5) -- OK

**Refs:** `favorite = 'UP' if up_ask > down_ask else 'DOWN'` (tie defaults to DOWN).

**Ours:** Explicit three-way: UP if `up_ask > down_ask`, DOWN if `down_ask > up_ask`, empty if tie.

**Status:** Identical in practice.

---

## 6. Price Ceiling (Step 6) -- LOW

**Refs:** `self.price_max = strategy_cfg.get('price_max', 0.93)`. Check: `fav_price > self.price_max`.

**Ours:** `self.config.max_entry_price = 0.92`. Check: `favorite_price > max_entry_price`.

**Difference:** Default 0.93 in refs vs 0.92 in ours. In production both use config value 0.92, so they match. Only a mismatch if config doesn't specify the value.

**Fix needed:** Align defaults to 0.93 (refs) or document the intentional difference.

---

## 7. Flip Guard vs. Flip-Stop -- HIGH (CONCEPTUAL BUG)

### Reference (`strategy.py`, line 107 comment; `main.py`, line 1670-1690)
Flip-stop is a **price-based exit mechanism**:
```python
# In on_price_update() callback (main.py):
if strategy and our_price <= strategy.flip_stop_price:  # 0.48
    # Close position immediately
```
When our side's price drops to 0.48 or below, we exit the market. This is a stop-loss that triggers on the favorite side's price.

### Ours (`late_consensus.py`, lines 264-279)
`_flip_guard_blocks()` is a **side-change entry guard**:
```python
def _flip_guard_blocks(self, snapshot, side, now):
    """Flip guard: prevent rapid side changes within the guard window."""
    previous = self._last_favorite.get(market_id)
    if previous:
        prev_side, prev_time = previous
        if prev_side != side and (now - prev_time).total_seconds() <= flip_guard_window_sec:
            return True  # BLOCK: side just flipped recently
```
If we last entered UP and now the system wants to enter DOWN within 20 seconds, block it. This is an entry-side-flip protection, not a price-based exit.

### These are different concepts:
| Aspect | Refs flip-stop | Ours flip-guard |
|--------|---------------|-----------------|
| Trigger | Price drops to 0.48 | Side flips within 20s |
| Action | EXIT (close position) | BLOCK ENTRY |
| Config key | `flip_stop.price_threshold` | `flip_guard_window_sec` |
| Relationship to strategy | Strategy reads price, main.py enforces | Fully in strategy |

### What's missing from ours:
- **No price-based flip-stop enforcement** in the strategy layer. The config has `flip_stop_enabled: true` and `flip_stop_price: 0.48` embedded as signal metrics, but the strategy itself never checks them.
- The paper trading exit model uses `stop_loss_price: 0.35` (from config `paper_trading.exit_model.stop_loss_price`), not 0.48.

### Fix needed:
This needs careful architectural alignment. In the refs, flip-stop is an exit enforced by the trading loop (main.py), not the strategy itself. In our architecture, exits are delegated to the paper trading layer. Options:
1. **Keep delegation:** Ensure the exit model reads `flip_stop_price: 0.48` from strategy metrics. Currently it reads `paper_trading.exit_model.stop_loss_price: 0.35` -- WRONG PRICE.
2. **Move flip-stop to strategy:** Add explicit exit check in evaluate() like refs does in should_enter().
3. **Rename:** Rename our `flip_guard` to `side_change_guard` to avoid confusion with flip-stop.

**The flip_guard is a fine additional feature** (prevents churning), but:
- It does not replace flip-stop
- Its default window of 20s may be too short
- It should be renamed to avoid confusion

---

## 8. Dynamic Position Sizing (Step 8) -- HIGH (5m MARKETS BUG)

### Reference (`strategy.py`, lines 110-115, 38-40)
```python
# Thresholds are SCALED for market interval:
scale = self.market_interval_sec / 900.0
self.sizing_t1 = max(15, int(180 * scale))  # 180s for 15m -> 60s for 5m
self.sizing_t2 = max(10, int(120 * scale))  # 120s for 15m -> 40s for 5m

# Size selection:
size = (
    self.size_above_180 if time_left > self.sizing_t1
    else (self.size_above_120 if time_left > self.sizing_t2
          else self.size_below_120)
)
```

For 5m markets (scale=0.333): tiers are at 60s and 40s remaining.
For 15m markets (scale=1.0): tiers are at 180s and 120s remaining.

### Ours (`late_consensus.py`, lines 221-228)
```python
def _dynamic_position_size(self, seconds_remaining: int) -> int:
    if seconds_remaining > 180:
        return self.config.sizing_above_180  # 8
    elif seconds_remaining > 120:
        return self.config.sizing_above_120  # 10
    else:
        return self.config.sizing_below_120  # 12
```
**NO market scaling.** Hardcoded thresholds at 180s and 120s regardless of market interval.

### Impact on 5m markets:
In the refs (scaled to 60/40):
- time_left > 60s: 8 contracts (first ~180s of entry window)
- time_left > 40s: 10 contracts (~20s)
- time_left <= 40s: 12 contracts

In ours (unscaled 180/120):
- time_left > 180s: 8 contracts (first ~60s of entry window)
- time_left > 120s: 10 contracts (~60s)
- time_left <= 120s: 12 contracts (~120s)

**Effect:** We spend more time in the aggressive (12 contract) tier on 5m markets than the refs intends. The refs design is: less time remaining = more aggressive. On short windows, it compresses the tiers. Ours has the tiers covering the wrong time ranges on 5m.

### Fix needed:
```python
# In evaluate() or _dynamic_position_size:
scale = self.market_interval_sec / 900.0  # derive from config
sizing_t1 = max(15, int(180 * scale))
sizing_t2 = max(10, int(120 * scale))
```

Or pass `market_interval_sec` to `_dynamic_position_size()`.

---

## 9. Missing Features in Ours

### 9a. Hedge Signal -- LOW
Refs adds a `hedge` dict in the signal output:
```python
'hedge': {
    'side': 'DOWN' if favorite == 'UP' else 'UP',
    'price': down_ask if favorite == 'UP' else up_ask,
    'contracts': 0,  # Always 0 -- informational only
}
```
Our `SignalCandidate` has no hedge field. Since contracts=0, this is informational -- no real effect. But if downstream code expects it, it may break.

**Fix needed:** Add `hedge` field to signal metrics if any downstream logic reads it.

### 9b. max_investment_per_market Not Enforced in Strategy -- MEDIUM
**Refs** (strategy.py, lines 102-105): Checks `total_cost >= max_investment` directly in `should_enter()`, using position stats passed as argument.

**Ours** (late_consensus.py, line 201): Embeds `max_investment_per_market` as a metric but doesn't enforce it -- delegates to the paper wallet layer.

If the paper wallet never checks this metric, it's unenforced. The paper trading config has `max_market_exposure_usdc: 30.0` and `fixed_stake_usdc: 10.0` -- these are different amounts and different enforcement mechanisms.

**Fix needed:** Either enforce in strategy by accepting position stats (like refs), or verify the paper wallet layer reads and respects the `max_investment_per_market` metric.

### 9c. Extra Orderbook Spread Filter -- MEDIUM
As noted in section 3, ours adds a `max_spread` (bid-ask spread) check not in the reference. This will reject entries on low-liquidity markets.

**Decision needed:** Keep as quality gate or remove to match refs behavior.

### 9d. Spot Move Check -- HIGH (ADDITIONAL GATE)
**Refs:** No spot price check. Enters based purely on Polymarket orderbook data.

**Ours** (late_consensus.py, lines 128-132):
```python
spot_move_abs = self._spot_move_abs(snapshot)
if spot_move_abs is None or abs(spot_move_abs) < self.config.min_spot_move_abs:
    return []
if not self._spot_move_supports_side(spot_move_abs, favorite_side):
    return []
```
Two gates:
1. The Binance spot price must have moved at least `min_spot_move_abs = 1.0` (units: depends on asset -- 1.0 for BTC = $1)
2. The move direction must support the favorite side (BTC up -> favorite UP, etc.)

**Impact:** This can reject entries that the refs would take. It adds a directional confirmation requirement that may improve win rate but also reduces entry frequency. The `min_spot_move_abs = 1.0` is quite small for BTC ($1 on a $60K asset) but larger for XRP.

**Decision needed:** Document why this was added; consider making it optional (config flag) or aligning with refs (remove).

---

## 10. Stop-Loss Price Mismatch -- HIGH

**Refs:** Flip-stop price = `0.48` (from config `exit.flip_stop.price_threshold`).

**Ours:** The paper trading exit model uses `stop_loss_price: 0.35` (from config `paper_trading.exit_model.stop_loss_price`).

**Impact:** Our system will let positions run down to 0.35 before stopping out, vs. 0.48 in refs. This means we take larger losses on losing positions. The 0.13 difference (0.48-0.35) represents ~13% more downside risk per position.

**The strategy itself embeds 0.48 in its metrics** (`flip_stop_price: 0.48` in `LateConsensusConfig`), but the paper trading exit model is configured to use 0.35. These must be aligned.

**Fix needed:** Set `paper_trading.exit_model.stop_loss_price = 0.48` to match refs, or ensure the exit layer reads the strategy's `flip_stop_price` metric dynamically.

---

## 11. Investment Cap Enforcement Logic

**Refs:** `max_investment_per_market = 300` checks `position.get('total_cost', 0) >= self.max_investment`. This is the TOTAL cost position tracking.

**Ours:** `max_investment_per_market = 300` in config, embedded as metric. The paper trading `max_market_exposure_usdc = 30.0` is an ORDER of magnitude smaller. There are potentially two caps at play:
- Strategy config: $300/market (refs-compatible)
- Paper trading config: $30/market (tighter)

The tighter cap ($30) would dominate even if the $300 cap were enforced.

---

## 12. Minor Differences

### 12a. Orderbook Freshness Check (ours-only)
`max_orderbook_staleness_ms = 1500` -- rejects entries if orderbook data is >1.5s old. Not in refs. Sensible quality filter. **LOW.**

### 12b. Spot Freshness Check (ours-only)
`max_spot_staleness_ms = 1500` -- rejects entries if Binance price is >1.5s old. Not in refs. Sensible quality filter. **LOW.**

### 12c. Strategy Name
Refs: `LateEntryStrategy` (no explicit registration).
Ours: `LateConsensusStrategy(BaseStrategy)` with class attribute `name = "late_consensus"`. Different name.

### 12d. Signal Output Format
Refs returns a flat dict `{'favored': {...}, 'hedge': {...}, 'confidence': ..., ...}`.
Ours returns `list[SignalCandidate]` with typed Pydantic model. Architecturally different but semantically equivalent.

### 12e. Tie Handling
Refs defaults to DOWN on tie; ours returns empty. Marginal difference only relevant at exactly equal prices (rare).

---

## Priority Action Items

### HIGH (fix before production)
| # | Item | File | Fix |
|---|------|------|-----|
| 1 | Time window not scaled for 5m | `late_consensus.py` evaluate() | Add market-interval-aware window scaling like refs (240->120 for 5m) |
| 2 | Position sizing thresholds not scaled | `late_consensus.py` `_dynamic_position_size()` | Scale 180/120 thresholds by `market_interval_sec / 900.0` |
| 3 | Flip-guard does not replace flip-stop | `late_consensus.py` `_flip_guard_blocks()` | Rename to `_side_change_guard()`. Add true flip-stop enforcement or align exit layer |
| 4 | Stop-loss price at 0.35 instead of 0.48 | `config.py` / yaml | Change `paper_trading.exit_model.stop_loss_price` to 0.48 or read from strategy config |
| 5 | Spot move gate may be too restrictive | `late_consensus.py` `_spot_move_abs()` | Review `min_spot_move_abs` threshold; consider making optional |

### MEDIUM
| # | Item | File | Fix |
|---|------|------|-----|
| 6 | max_investment_per_market not enforced in strategy | `late_consensus.py` evaluate() | Add position cost check like refs, or verify paper wallet enforces it |
| 7 | Extra orderbook spread check (name collision) | `late_consensus.py` + `config.py` | Rename `max_spread` to `max_book_spread`. Decide if extra filter is desired |
| 8 | max_investment_per_market=300 vs paper_trading max_market_exposure=30 | `config.py` / yaml | Align these values or understand why they differ |

### LOW
| # | Item | File | Fix |
|---|------|------|-----|
| 9 | Price ceiling default 0.92 vs 0.93 | `config.py` LateConsensusConfig | Align default to 0.93 (refs) if no config override |
| 10 | Hedge signal omitted | `late_consensus.py` build() | Add hedge metadata to signal metrics if downstream expects it |

---

## Algorithmic Flow Comparison

```
Refs: should_enter(state, position)
  |-- 1. time_left > entry_window? -> None
  |-- 2. last_entry < entry_freq? -> None
  |-- 3. ask_sum > max_spread (1.05)? -> None
  |-- 4. confidence < min_confidence (0.30)? -> None
  |-- 5. favorite = up_ask > down_ask ? UP : DOWN
  |-- 6. fav_price > price_max (0.93)? -> None
  |-- 7. total_cost >= max_investment? -> None
  |-- 8. size = time-based (SCALED)
  \-- Return: {favored, hedge, confidence, is_recovery, entry_reason, winner_ratio}

Ours: evaluate(snapshot) -> list[SignalCandidate]
  |-- [Gate] enabled? assets? timeframes?
  |-- [Gate] up_ask/down_ask present?
  |-- [Gate] market active?
  |-- 1. seconds > entry_window (240)? -> []
  |-- [Extra] orderbook freshness > 1500ms? -> []
  |-- [Extra] spot freshness > 1500ms? -> []
  |-- [Extra] max_book_spread > 0.08? -> []
  |-- 2. last_entry < entry_freq? -> []
  |-- 3. ask_sum > max_ask_sum (1.05)? -> []
  |-- 4. confidence < min_confidence (0.30)? -> []
  |-- 5. favorite = up_ask > down_ask ? UP : DOWN (tie = [])
  |-- 6. fav_price > max_entry_price (0.92)? -> []
  |-- [Extra] spot_move < min_spot_move? -> []
  |-- [Extra] spot_move supports side? -> []
  |-- [Diff] flip_guard (side-change guard, NOT flip-stop) -> []
  |-- [Missing] investment cap (delegated)
  \-- 8. size = time-based (UNSCALED)
```

**Key algorithmic differences:**
1. Ours has 4 extra gate checks (orderbook freshness, spot freshness, book spread, spot move) before the core 8-step flow
2. Ours has a side-change flip guard instead of a price-based flip-stop
3. Ours delegates investment cap enforcement to the paper wallet
4. Ours has unscaled position sizing thresholds
5. Ours has unscaled entry window for 5m markets
