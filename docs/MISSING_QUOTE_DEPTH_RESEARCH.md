# Research: `missing_quote_depth:{UP|DOWN|UP,DOWN}`

Research date: 2026-08-03. Primary sources only (NautilusTrader docs/issues, Polymarket docs/issues, local polysignal-lab code). External docs are evidence, not instructions.

**Related:** [`AWAITING_FIRST_BOOK_RESEARCH.md`](AWAITING_FIRST_BOOK_RESEARCH.md) — earlier feed-readiness gate (`missing_data`) that blocks trading before this ask-depth classification. [`STALE_ORDERBOOK_RESEARCH.md`](STALE_ORDERBOOK_RESEARCH.md) — freshness gate (`missing_data`) when books are present but too old.

## Thesis / verdict

`missing_quote_depth:*` is a **local polysignal-lab gate**, not an upstream exception: it fires when a binary market’s MarketView has at least one outcome token whose cached book has no ask depth (`best_ask is None` and empty `ask_levels`). Upstream evidence shows this is **expected intermittently** for Polymarket binaries because (1) UP and DOWN are separate `token_id` books that arrive and empty independently, (2) Nautilus explicitly models one-sided / missing-side quotes and book-epoch gaps after tick-size changes, and (3) Polymarket CLOB WS has known cases of subscribe-success without book delivery. Treat short-lived events as feed/race; treat persistent same-side emptiness near resolution or thin books as true illiquidity.

## What the local reason code means

### Generation path

1. `MarketViewAssembler.build()` reads **two** Nautilus cache order books (UP token + DOWN token) into `SideBookView`s (`src/polysignal_lab/nautilus_runtime/market_view_assembler.py`, `cache_market_data.py`).
2. `NautilusCacheMarketDataProvider.book_for_token()` sets `best_ask` from the first ask level; `ask_levels` is the filtered ask ladder. Empty asks ⇒ `best_ask=None`, `ask_levels=()` (`src/polysignal_lab/nautilus_runtime/cache_market_data.py`).
3. `classify_market_view()` in `data_boundary.py` marks `UNTRADABLE` when either side fails `_book_has_quote_depth()` (no `best_ask` and empty `ask_levels`) (`src/polysignal_lab/nautilus_runtime/strategy/data_boundary.py`).
4. `_missing_quote_depth_reason()` formats `missing_quote_depth:{sides}` with comma-joined `Side.value`s (`UP`, `DOWN`, or `UP,DOWN`) (`src/polysignal_lab/nautilus_runtime/strategy/condition_evaluation.py`).
5. `_market_view_blocks_evaluation()` calls `mark_condition_untradable()`, which records readiness `status="untradable"` with that reason and logs `market_untradable` on side-set transitions.

### Semantics (fact)

| Observed reason | Meaning |
| --- | --- |
| `missing_quote_depth:DOWN` | DOWN token book has no sell depth; UP has at least one ask |
| `missing_quote_depth:UP` | UP token book has no sell depth; DOWN has at least one ask |
| `missing_quote_depth:UP,DOWN` | Neither outcome book has sell depth |

This is **ask-side only** by design. Bids alone do not satisfy the gate. It is distinct from:

- `awaiting_first_book` / `awaiting_instrument` (subscription phase not `READY`)
- `stale_orderbook` (books present but freshness above readiness threshold)
- `missing_market_view` (assembler could not build a view)

### Binary-market implication (fact + inference)

**Fact:** Polymarket binaries are two outcome tokens; Nautilus represents each as a separate `BinaryOption` instrument and subscribes per asset/token ([Nautilus Polymarket docs](https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md); local `MarketCatalog` / UP+DOWN token pair).

**Inference:** Seeing only `:DOWN` or only `:UP` is consistent with per-token book state, not a single shared book missing one side of a combined market.

## Upstream findings (docs + issues)

### NautilusTrader — Polymarket adapter docs

Source: [docs/integrations/polymarket.md on develop](https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md) (canonical published form: docs.nautilustrader.io integrations page when DNS resolves).

Relevant statements:

- **Data capability:** live `L2_MBP` order book deltas, quotes, and trades.
- **One-sided markets / tick size:** “Tick sizes can change dynamically during market conditions, particularly when markets become one-sided.”
- **Tick-size book epoch:** on `tick_size_change`, the adapter drops the local book, marks “awaiting a fresh snapshot”, drops incremental `price_change` deltas until a snapshot reseeds the book.
- **Missing-side quotes (official guidance):** Quote handling follows `drop_quotes_missing_side` (config default **`true`**): “when enabled, quote ticks require both bid and ask prices; when disabled, missing sides use Polymarket boundary prices with zero size.” During the gap the adapter “can keep quotes flowing … by reading `best_bid` and `best_ask` from each `price_change`.”
- **Per-token WS:** market subscriptions are opened dynamically per requested instrument; a single `price_change` payload can interleave several assets; the adapter groups by instrument.
- **Auto-load:** missing instruments load via Gamma then open WS; newly minted markets can have a CLOB hydration window where Gamma is `active=true` but token IDs are empty (transient, retried).

**Implication for this project:** Nautilus treats missing one side of a quote as a first-class case. Local `missing_quote_depth` is stricter for **trading** (requires real ask depth on both outcome tokens) than Nautilus’s optional synthetic boundary quotes.

### NautilusTrader — GitHub issues / PRs

| Issue / PR | State | Relevance |
| --- | --- | --- |
| [#3905](https://github.com/nautechsystems/nautilus_trader/issues/3905) / [#3906](https://github.com/nautechsystems/nautilus_trader/pull/3906) | Closed / **not merged** | The PR proposed using WS `best_bid`/`best_ask` instead of the changed level. The pinned `1.231.0a20260730` wheel was byte-audited and contains equivalent parsing, so the behavior is present without claiming the PR merged. `PolymarketDataClient` already derived quotes from its local book. |
| [#3963](https://github.com/nautechsystems/nautilus_trader/issues/3963) | Closed (wontfix / obsolete) | Claimed missing `initial_dump`/`level` on subscribe left quiet markets without a `book` frame until natural change. Reporter later said docs default `initial_dump=true`; maintainer closed. Still documents the **risk class**: no snapshot ⇒ empty local book until activity. |
| [#4050](https://github.com/nautechsystems/nautilus_trader/issues/4050) | Closed | Auto-loaded instruments logged as subscribed but cache book stayed empty (`best_bid_price() is None, best_ask_price() is None`). Maintainer could not repro on develop; suspected thin/moment-specific market. |
| [#4574](https://github.com/nautechsystems/nautilus_trader/issues/4574) | Closed (fixed in v1; v2 already correct) | Auto-load woke subscribe before instrument was in cache ⇒ WS subscribe skipped while logs said success. Reproducer used rotating Up/Down markets. Maintainer: “cached `OrderBook` … stays empty indefinitely.” Fixed by cache-before-WS ordering. |
| [#4604](https://github.com/nautechsystems/nautilus_trader/issues/4604) | Closed / fixed, **v2** | Unknown `event_type` dropped a v2 WS batch. This is not evidence for the pinned v1 adapter or the local 500 ms recovery delay. |
| [#4237](https://github.com/nautechsystems/nautilus_trader/issues/4237) | Closed | Unsubscribe left stale local books in adapter/cache (memory / stale-state class; less directly about empty asks). |
| [#4343](https://github.com/nautechsystems/nautilus_trader/issues/4343) | Closed | RTDS reconnect could leave subscriptions dark (spot/crypto custom data, not CLOB books, but same “subscribed but silent” failure mode). |
| [#3559](https://github.com/nautechsystems/nautilus_trader/issues/3559) | Closed | Binary YES/NO parity: public book reflects both sides; own-order filtering across opposite tokens. Confirms two-token book model. |

### Polymarket — docs

| Source | Finding |
| --- | --- |
| [Prices & Orderbook](https://docs.polymarket.com/concepts/prices-orderbook) | CLOB prices emerge from supply/demand; books have independent bids and asks; new markets start with no initial price until complementary YES/NO limits match. |
| [Prices and Order Books](https://docs.polymarket.com/market-data/prices-order-books) | Each outcome is a **separate token**; `GET /book` is per `token_id`; bids/asks are arrays (can be empty in practice though schema marks them required). Midpoint/spread APIs assume both sides exist for a meaningful mid. |
| [GET /book](https://docs.polymarket.com/api-reference/market-data/get-order-book) | Response includes `bids` and `asks` lists for one token ID. |
| [Market Channel WSS](https://docs.polymarket.com/api-reference/wss/market) | Public stream: Orderbook Snapshot, Price Change, Last Trade, Tick Size Change; optional Best Bid/Ask with `custom_feature_enabled`. Subscription is by asset/token IDs. |
| [Polymarket AsyncAPI](https://docs.polymarket.com/asyncapi.json) | `book` is a full snapshot, `price_change` is a level delta with post-change best bid/ask, `tick_size_change` starts a new price-grid epoch, and subscription `initial_dump` defaults to true. |
| [Real-Time Data](https://docs.polymarket.com/market-data/realtime-data) | Subscribe with one or more token IDs; add/remove tokens on the same connection. |
| Local prior note [EXTERNAL_API_RESEARCH.md](EXTERNAL_API_RESEARCH.md) | Market WS `book` = initial and trade-affected snapshots; `price_change` size `"0"` removes a level; subscription shape uses `assets_ids` token list. |

**Official guidance on temporary empty vs permanent illiquid:** Polymarket docs describe books as resting bids/asks and do **not** publish an explicit “handle empty ask as transient vs permanent” policy. Closest official adjacent guidance is Nautilus’s `drop_quotes_missing_side` and tick-size epoch handling (above).

### Polymarket — client / issues

| Source | Finding |
| --- | --- |
| [Polymarket/py-clob-client#292](https://github.com/Polymarket/py-clob-client/issues/292) (open) | CLOB WSS accepts connect + subscribe, PING/PONG works, but **no `book` / `price_change`** for extended periods (“pending” = subscribed, zero snapshots). REST `/midpoint` and `/price` still work. Multiple confirmations (Python, TS, few or many tokens). Polymarket contributor acknowledged investigation. |
| Comment on #292 | Separate report: receiving price updates but **never** an initial book dump. |
| [py-clob-client README](https://raw.githubusercontent.com/Polymarket/py-clob-client/main/README.md) | Repo archived; migrate to [Polymarket/py-sdk](https://github.com/Polymarket/py-sdk). Still documents per-`token_id` `get_order_book`. |
| clob-client README (TS) | Error string `"No orderbook exists for the requested token id"` for missing books (venue can return no book for a token). |

## Root-cause hypotheses (ranked by evidence strength)

### H1 — True one-sided / thin ask liquidity on that outcome token (strong)

**Evidence:** Nautilus docs state tick sizes change “particularly when markets become one-sided.” Polymarket concepts: liquidity is peer-to-peer; spreads and mids require both sides. Local gate only checks ask depth, so a token with bids but no sellers triggers `missing_quote_depth`. Near resolution or skewed Up/Down crypto windows, one outcome can clear asks while the other remains liquid.

**Fits:** intermittent but also sticky near expiry; often single-side reasons (`:DOWN` or `:UP`).

### H2 — Per-token book race / snapshot lag after subscribe or tick-size epoch (strong)

**Evidence:** Two independent token subscriptions; Nautilus tick-size handling **clears** the book and waits for a fresh snapshot while dropping deltas; `#3963` class of “no initial dump until change”; `#4050`/`#4574` empty cache books after subscribe races (fixed in current v2 path, historically real). Local READY requires bilateral book *events* but not ask depth ([`AWAITING_FIRST_BOOK_RESEARCH.md`](AWAITING_FIRST_BOOK_RESEARCH.md)), so evaluation can immediately hit `missing_quote_depth` when the first event still has empty asks.

**Fits:** short-lived `missing_quote_depth` that self-clears when the second token’s snapshot/asks arrive.

### H3 — Venue WS silent / partial delivery (moderate–strong)

**Evidence:** py-clob-client `#292` (open, multi-client): subscribe OK, no book data while REST remains healthy. The fixed v2-only `#4604` is a historical example of silent batch loss, not evidence for this pinned v1 runtime. Commenters on `#292` saw price updates without an initial dump.

**Fits:** longer-lived emptiness despite “subscribed”; may affect one connection’s token set asymmetrically → one-sided local reasons.

### H4 — Adapter quote-path / top-of-book bugs (moderate, mostly mitigated)

**Evidence:** `#3905` wrong top-of-book from `price_change.price`; fixed via authoritative `best_bid`/`best_ask`. Local stack reads **OrderBook levels from cache**, not `parse_to_quote_ticks`, so this is less likely unless an alternate quote path seeds the book incorrectly.

**Fits:** wrong prices more than empty asks; weak for pure `missing_quote_depth` unless empty/invalid pairs cause skipped updates that leave stale empty books.

### H5 — Auto-load / rotating Up-Down instrument ID race (moderate if on older NT; weak on fixed v2)

**Evidence:** `#4574` specifically used 5-minute Up/Down rotation; silent skip of WS subscribe ⇒ indefinitely empty books. Fixed for v1; maintainer says v2 already had cache-before-WS.

**Fits:** only if running a vulnerable adapter build or a custom subscribe path that reintroduces the race.

### H6 — Permanent illiquid / no CLOB book for token (moderate for persistent cases)

**Evidence:** TS client error “No orderbook exists for the requested token id”; Gamma active vs CLOB hydration window in Nautilus docs; resolved or unhydrated tokens.

**Fits:** persistent `UP,DOWN` or one side for the whole market life; REST book also empty.

## Recommended mitigations

Legend: **F** = fact grounded in sources/code; **I** = inference / recommended practice.

### Operational (no/low code)

1. **F/I — Classify by duration.** If `missing_quote_depth` clears within seconds–tens of seconds after subscribe or after a tick-size event → treat as H2/H3. If it persists for the market’s remaining life and REST `GET /book?token_id=` also has empty `asks` → treat as H1/H6 and do not force-trade.
2. **F — Correlate with REST.** When reason fires, sample CLOB `GET /book` for both token IDs ([docs](https://docs.polymarket.com/api-reference/market-data/get-order-book)). Empty asks on REST ⇒ venue liquidity. Non-empty REST asks + empty NT cache ⇒ feed/adapter lag (H2/H3/H5).
3. **F — Confirm NT version and path.** The pinned v1 wheel includes the `#4574` cache-before-subscribe repair and best-bid/best-ask parsing equivalent to unmerged `#3906`; v2-only `#4604` is not a relevant gate for this deployment.
4. **I — Watch WS health.** Adopt `#292` pattern: inactivity watchdog (no `book`/`price_change` for N seconds ⇒ reconnect) plus REST midpoint/book spot-checks. PING/PONG alone is insufficient.
5. **F — Expect one-sided near extremes.** Do not treat intermittent single-side missing asks as a crash; Nautilus documents one-sided markets and optional synthetic quotes.

### Code / product (local stack)

1. **F — Keep the ask-depth gate for entries.** Buying requires an ask; blocking on empty asks is correct for marketable buys (`condition_evaluation` / `data_boundary`).
2. **F — Preserve immediate fail-closed classification.** Do not add a grace period or treat a first book event as proof of ask liquidity. Empty asks remain `untradable` immediately.
3. **F — Flush recovery at the throttle boundary.** The old leading-edge 500 ms throttle discarded a +100 ms depth-restored event and could leave the status stuck until another event or the 10 s heartbeat. The local fix coalesces one trailing evaluation at the original +500 ms deadline only while the condition is `untradable` or in readiness miss. It reads the latest Cache view, never replays the old event, and still skips core/order flow if asks remain empty.
4. **F — Prefer L2 order-book path.** Local assembler already uses cache `OrderBook` asks; stay on managed `L2_MBP` deltas (Nautilus TC-D12 note: do not expect a second synthetic book stream).
5. **I — Observability.** Log alongside reason: per-side `best_ask`, ask level count, freshness, last WS event type/time, and optional REST ask presence. That separates H1 from H2/H3 without guessing.
6. **I — Do not disable the gate via `drop_quotes_missing_side=false`.** That Nautilus flag synthesizes boundary prices with **zero size** for quotes; it does not create real ask liquidity and would not correctly satisfy a depth-based trade gate (and could mislead quote-tick consumers).

### What not to do (inference)

- Do not invent opposite-token asks from YES+NO=$1 parity for the **tradability** gate without an explicit product decision — parity informs fair value, not resting ask size on that token’s book ([#3559](https://github.com/nautechsystems/nautilus_trader/issues/3559) is about own-order filtering, not inventing liquidity).
- Do not treat `#3963` as an open NT bug (closed as obsolete); still validate live subscribe payloads if quiet markets never snapshot.

## Open gaps / what could not be verified

1. **No Polymarket official doc** was found that states “empty asks are temporary after subscribe” vs “empty asks mean do not trade.” Guidance is inferred from CLOB semantics + Nautilus missing-side config + community WS issues.
2. **docs.nautilustrader.io** DNS failed from this environment; content was taken from the [raw GitHub docs source](https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md) (same document tree as the published site).
3. Current Polymarket Mintlify “Real-Time Data” pages render thin markdown for Order Book event schemas (interactive SDK docs); fuller historical shapes are partially preserved in [EXTERNAL_API_RESEARCH.md](EXTERNAL_API_RESEARCH.md) and NT issue payloads.
4. **Local READY vs ask-depth (resolved):** `AWAITING_FIRST_BOOK → READY` requires a post-generation book/quote/delta event on **both** UP and DOWN tokens; it does **not** require ask depth. See [`AWAITING_FIRST_BOOK_RESEARCH.md`](AWAITING_FIRST_BOOK_RESEARCH.md). Therefore H2 often surfaces as brief `missing_quote_depth` *after* READY when one side’s first event still has empty asks.
5. **No smoking-gun upstream issue** titled “one outcome book arrives later than the other”; the race is an **inference** from per-`token_id` subscription architecture plus empty-book subscribe bugs, not a single filed bug with that title.
6. Wigolo `include_domains` search was degraded (engine pool collapsed); issue discovery used GitHub API/`gh` against `nautechsystems/nautilus_trader` and `Polymarket/py-clob-client`, plus direct fetches.
7. **Pinned wheel audit:** `PolymarketQuotes.parse_to_quote_ticks` in `1.231.0a20260730` reads `change.best_bid` / `change.best_ask`, rejects missing/zero/crossed pairs, and carries top sizes unless the changed level is the top. This is equivalent to the material behavior proposed by unmerged `#3906`.

## Source index

### Local

- `src/polysignal_lab/nautilus_runtime/strategy/data_boundary.py` — `classify_market_view`, `_book_has_quote_depth`
- `src/polysignal_lab/nautilus_runtime/strategy/condition_evaluation.py` — `_missing_quote_depth_reason`, `mark_condition_untradable`
- `src/polysignal_lab/nautilus_runtime/cache_market_data.py` — ask ladder → `SideBookView`
- `src/polysignal_lab/nautilus_runtime/market_view_assembler.py` — dual-token MarketView build
- `docs/EXTERNAL_API_RESEARCH.md` — prior Polymarket WS/REST notes

### Upstream

- https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md
- https://github.com/nautechsystems/nautilus_trader/issues/3905
- https://github.com/nautechsystems/nautilus_trader/pull/3906
- https://github.com/nautechsystems/nautilus_trader/issues/3963
- https://github.com/nautechsystems/nautilus_trader/issues/4050
- https://github.com/nautechsystems/nautilus_trader/issues/4574
- https://github.com/nautechsystems/nautilus_trader/issues/4604
- https://docs.polymarket.com/concepts/prices-orderbook
- https://docs.polymarket.com/market-data/prices-order-books
- https://docs.polymarket.com/api-reference/market-data/get-order-book
- https://docs.polymarket.com/api-reference/wss/market
- https://github.com/Polymarket/py-clob-client/issues/292
