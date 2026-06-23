# Telegram Notification Template Redesign

## Goal

Make Telegram notifications easier to scan and less noisy while staying compatible with the current Telegram publishing pipeline.

## Source context

- Current message templates live in `src/polysignal_lab/signal_layer/formatter.py`.
- Current publisher uses Telegram Bot API `sendMessage` with `parse_mode="HTML"` in `src/polysignal_lab/publish/telegram_publisher.py`.
- Telegram Bot API `sendMessage` accepts `text` of 1–4096 characters after entity parsing and supports HTML formatting tags such as `<b>`, `<i>`, `<u>`, `<code>`, and `<blockquote>`.
- Telegram Bot API 10.1 added `sendRichMessage`, but this change does not need a new sending method.

## Decision

Use the existing `sendMessage + parse_mode="HTML"` path and redesign only the formatter output.

This is the safest implementation because it avoids API migration risk, preserves existing tests around publishing, and still enables a cleaner visual style through supported HTML tags and emoji.

## Scope

Update these generated message types:

1. `signal` via `MessageFormatter.signal_message`
2. `paper_result` via `MessageFormatter.result_message`
3. `daily_report` via `MessageFormatter.daily_report_message`
4. Telegram QA default message if needed for consistency

No new Telegram API method, no media messages, no inline keyboard, and no dashboard changes.

## Content rules

Remove verbose risk and disclaimer text:

- `Risk:` section
- `Manual execution only`
- `Do not chase above max entry`
- `This is a signal, not financial advice`
- `No profit guarantee`
- `No real order was placed`
- `No real trades were placed`
- Repetitive long `[PolySignal Lab ...]` titles

Keep a compact paper-trading marker where useful:

- Signal and paper-result messages end with `Mode: Paper`.
- Daily report title already includes `Paper`, so it does not need another mode line.

## Template design

### Signal

```html
<b>🟢 BTC 15m · BUY UP</b>
<code>ptb_diff</code>

Entry  0.4321
Max    0.4600
Stake  10.00 USDC
Conf   82%
Close  14:02

<b>Why</b>
• PRICE_TO_BEAT_EDGE
• BOOK_SPREAD_OK
• FRESH_ORDERBOOK

Mode: Paper
ID: <code>sig_95488445cbf35e696223</code>
```

Fields:

- Asset, timeframe, action, and side in the headline.
- Strategy on the second line in `<code>`.
- Prices and sizing as compact aligned rows.
- Reason codes as bullet rows.
- Signal ID in `<code>`.

### Paper result

WIN example:

```html
<b>✅ BTC 15m · WIN</b>
<code>ptb_diff</code>

Side   UP
Entry  0.4321
Stake  10.00 USDC
Shares 23.1428

PnL    +13.1428 USDC
ROI    +131.43%
Settle 23.1428 USDC

Mode: Paper
ID: <code>sig_95488445cbf35e696223</code>
```

LOSS example:

```html
<b>🔴 BTC 15m · LOSS</b>
<code>ptb_diff</code>

Side   UP
Entry  0.4321
Stake  10.00 USDC
Shares 23.1428

PnL    -10.0000 USDC
ROI    -100.00%
Settle 0.0000 USDC

Mode: Paper
ID: <code>sig_95488445cbf35e696223</code>
```

Result emoji mapping:

- `WIN` -> `✅`
- `LOSS` -> `🔴`
- all other statuses -> `⚪`

### Daily report

With closed trades:

```html
<b>📊 Daily Paper Report</b>
2026-06-23

Equity  1000.00 → 1018.75 USDC
PnL     +18.75 USDC
ROI     +1.88%

Signals 9
Filled  5
Closed  4
W/L     3 / 1
WR      75.00%

<b>Strategies</b>
• ptb_diff: 3 trades, 2W/1L, +11.25 USDC
• fibonacci_bot: 1 trade, 1W/0L, +7.50 USDC
```

No closed trades:

```html
<b>📊 Daily Paper Report</b>
2026-06-23

Equity  1000.00 → 1000.00 USDC
PnL     +0.00 USDC
ROI     +0.00%

Signals 9
Filled  5
Closed  0
W/L     0 / 0
WR      0.00%

<b>Strategies</b>
• No closed trades
```

Pluralization:

- Use `1 trade` for one closed trade.
- Use `N trades` otherwise.

## HTML escaping

All user-, market-, strategy-, and reason-code-derived text must continue to be escaped with `html.escape` before insertion into HTML output.

Numeric fields do not need escaping.

## Truncation

Keep the existing `MessageFormatter._truncate` behavior and Telegram max-character configuration. The redesigned messages should be shorter, so truncation becomes less likely.

## Tests

Update formatter tests to assert:

- New messages contain expected HTML headlines.
- Removed disclaimer/risk phrases are absent.
- `Mode: Paper` remains in signal and result messages.
- Daily report uses compact strategy rows and `• No closed trades` when empty.
- Long signal messages still truncate with `[truncated for Telegram]`.

Run targeted tests that cover formatter and Telegram publishing behavior.
