# Telegram Notification Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace noisy Telegram text notifications with compact HTML-formatted signal, paper-result, and daily-report templates.

**Architecture:** Keep the existing `TelegramPublisher.sendMessage` pipeline unchanged. Change only `MessageFormatter` output and formatter-focused tests so the publisher continues to send `parse_mode="HTML"` text under the existing max-character limit.

**Tech Stack:** Python 3.11, pydantic models, pytest, Telegram Bot API `sendMessage` with `parse_mode="HTML"`.

## Global Constraints

- Existing sender stays on `sendMessage + parse_mode="HTML"`; do not introduce `sendRichMessage`.
- Message text must remain <= configured `MessageFormatter.max_chars` through existing `_truncate` behavior.
- Escape all strategy, asset, timeframe, side, result, reason-code, and ID text with `html.escape` before inserting into HTML.
- Remove verbose risk and disclaimer copy: `Risk:`, `Manual execution only`, `Do not chase above max entry`, `not financial advice`, `No profit guarantee`, `No real order was placed`, `No real trades were placed`.
- Keep `Mode: Paper` in signal and paper-result messages; daily report title includes `Paper` and needs no extra mode line.
- Do not change dashboard, storage schema, Telegram credentials, or publish retry behavior.

---

## File Structure

- Modify `src/polysignal_lab/signal_layer/formatter.py`: rewrite `MessageFormatter.signal_message`, `result_message`, and `daily_report_message`; add tiny private helpers only if they reduce duplication without changing public API.
- Modify `src/polysignal_lab/publish/telegram_qa.py`: shorten `DEFAULT_MESSAGE` only if tests or copy consistency require it.
- Modify `tests/test_storage_reporting_publish.py`: update formatter assertions for compact templates, removed disclaimers, retained truncation.
- Modify `tests/test_reporting.py`: keep enum/report expectations compatible with the new daily-report wording.

---

### Task 1: Formatter tests for compact signal and result messages

**Files:**
- Modify: `tests/test_storage_reporting_publish.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_signal_message_within_limit tests/test_storage_reporting_publish.py::test_paper_result_and_daily_report_messages_are_paper_only -q`

**Interfaces:**
- Consumes: `MessageFormatter.signal_message(signal: SignalCandidate, stake_usdc: float) -> str`, `MessageFormatter.result_message(result: PaperTradeResult) -> str`
- Produces: failing tests that require compact HTML headlines, no verbose disclaimer text, and retained `Mode: Paper`.

- [ ] **Step 1: Write failing assertions for signal template**

In `tests/test_storage_reporting_publish.py::test_formatter_signal_message_within_limit`, replace the old paper-only/non-guarantee assertions with exact compact-template checks:

```python
assert "<b>🟢 " in message
assert " · BUY " in message
assert "</b>" in message
assert "<code>" in message
assert "Entry  " in message
assert "Max    " in message
assert "Stake  10.00 USDC" in message
assert "Conf   " in message
assert "Close  " in message
assert "<b>Why</b>" in message
assert "Mode: Paper" in message
assert "ID: <code>" in message
for removed in (
    "Risk:",
    "Manual execution only",
    "Do not chase above max entry",
    "not financial advice",
    "No profit guarantee",
    "No real order",
):
    assert removed not in message
```

- [ ] **Step 2: Write failing assertions for result template**

In `tests/test_storage_reporting_publish.py::test_paper_result_and_daily_report_messages_are_paper_only`, replace result-message disclaimer assertions with:

```python
assert result_message.startswith("<b>")
assert " · WIN</b>" in result_message
assert "<code>" in result_message
assert "Side   " in result_message
assert "Entry  " in result_message
assert "Stake  " in result_message
assert "Shares " in result_message
assert "PnL    " in result_message
assert "ROI    " in result_message
assert "Settle " in result_message
assert "Mode: Paper" in result_message
assert "ID: <code>" in result_message
for removed in (
    "Note:",
    "Paper result only",
    "No real order was placed",
    "No profit guarantee",
):
    assert removed not in result_message
```

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_signal_message_within_limit tests/test_storage_reporting_publish.py::test_paper_result_and_daily_report_messages_are_paper_only -q
```

Expected: FAIL because current messages still use `[PolySignal Lab]`, risk/disclaimer paragraphs, and no compact HTML headline.

---

### Task 2: Implement compact signal and result templates

**Files:**
- Modify: `src/polysignal_lab/signal_layer/formatter.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_signal_message_within_limit tests/test_storage_reporting_publish.py::test_paper_result_and_daily_report_messages_are_paper_only -q`

**Interfaces:**
- Consumes: failing tests from Task 1.
- Produces: compact HTML signal/result messages with same public `MessageFormatter` API.

- [ ] **Step 1: Update imports**

Keep the existing `html` import. Add enum import if needed:

```python
from polysignal_lab.domain.enums import TradeResultStatus
```

- [ ] **Step 2: Rewrite `signal_message` minimally**

Replace the body of `signal_message` with compact HTML output equivalent to:

```python
why = "\n".join(f"• {html.escape(code)}" for code in signal.reason_codes)
message = f"""<b>🟢 {html.escape(signal.asset)} {html.escape(signal.timeframe)} · {html.escape(signal.action.value)} {html.escape(signal.side.value)}</b>
<code>{html.escape(signal.strategy)}</code>

Entry  {signal.entry_reference_price:.4f}
Max    {signal.max_entry_price:.4f}
Stake  {stake_usdc:.2f} USDC
Conf   {signal.confidence:.0%}
Close  {self._format_seconds(signal.seconds_to_close)}

<b>Why</b>
{why}

Mode: Paper
ID: <code>{html.escape(signal.signal_id)}</code>"""
return self._truncate(message)
```

- [ ] **Step 3: Rewrite `result_message` minimally**

Use the existing sign logic and add result emoji:

```python
sign = "+" if result.pnl_usdc >= 0 else ""
match result.result:
    case TradeResultStatus.WIN:
        emoji = "✅"
    case TradeResultStatus.LOSS:
        emoji = "🔴"
    case _:
        emoji = "⚪"
message = f"""<b>{emoji} {html.escape(result.asset)} {html.escape(result.timeframe)} · {html.escape(result.result.value)}</b>
<code>{html.escape(result.strategy)}</code>

Side   {html.escape(result.side.value)}
Entry  {result.entry_price:.4f}
Stake  {result.stake_usdc:.2f} USDC
Shares {result.shares:.4f}

PnL    {sign}{result.pnl_usdc:.4f} USDC
ROI    {sign}{result.roi:.2%}
Settle {result.settlement_value:.4f} USDC

Mode: Paper
ID: <code>{html.escape(result.signal_id)}</code>"""
return self._truncate(message)
```

- [ ] **Step 4: Run tests to verify GREEN for signal/result**

Run the Task 2 test command.

Expected: PASS for the two targeted formatter tests.

---

### Task 3: Daily report tests and implementation

**Files:**
- Modify: `tests/test_storage_reporting_publish.py`
- Modify: `tests/test_reporting.py`
- Modify: `src/polysignal_lab/signal_layer/formatter.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_reporting.py -q`

**Interfaces:**
- Consumes: `MessageFormatter.daily_report_message(report: DailyReport) -> str`.
- Produces: compact daily report with strategy bullets and no disclaimer notes.

- [ ] **Step 1: Write failing daily-report assertions**

In `tests/test_storage_reporting_publish.py::test_paper_result_and_daily_report_messages_are_paper_only`, replace old daily disclaimer assertions with:

```python
assert daily_message.startswith("<b>📊 Daily Paper Report</b>")
assert "Equity  " in daily_message
assert " → " in daily_message
assert "PnL     " in daily_message
assert "ROI     " in daily_message
assert "Signals " in daily_message
assert "Filled  " in daily_message
assert "Closed  " in daily_message
assert "W/L     " in daily_message
assert "WR      " in daily_message
assert "<b>Strategies</b>" in daily_message
assert "•" in daily_message
for removed in (
    "Notes:",
    "Paper results only",
    "No real trades were placed",
    "No profit guarantee",
):
    assert removed not in daily_message
```

In `tests/test_reporting.py`, keep the `"SPLIT" not in message` assertion and add:

```python
assert message.startswith("<b>📊 Daily Paper Report</b>")
assert "<b>Strategies</b>" in message
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_paper_result_and_daily_report_messages_are_paper_only tests/test_reporting.py -q
```

Expected: FAIL because current daily report still has `[PolySignal Lab Daily Paper Report]` and `Notes:`.

- [ ] **Step 3: Rewrite daily report formatting**

In `daily_report_message`, build strategy rows like:

```python
lines = []
for strategy, row in report.strategy_breakdown.items():
    closed = row.get("closed_positions", 0)
    trade_word = "trade" if closed == 1 else "trades"
    lines.append(
        f"• {html.escape(strategy)}: {closed} {trade_word}, "
        f"{row.get('win_count', 0)}W/{row.get('loss_count', 0)}L, "
        f"{row.get('total_pnl_usdc', 0.0):+.2f} USDC"
    )
strategy_text = "\n".join(lines) if lines else "• No closed trades"
message = f"""<b>📊 Daily Paper Report</b>
{report.report_date.isoformat()}

Equity  {report.starting_equity:.2f} → {report.ending_equity:.2f} USDC
PnL     {report.paper_pnl:+.2f} USDC
ROI     {report.paper_roi:+.2%}

Signals {report.total_signals}
Filled  {report.paper_fills}
Closed  {report.closed_positions}
W/L     {report.win_count} / {report.loss_count}
WR      {report.win_rate:.2%}

<b>Strategies</b>
{strategy_text}"""
return self._truncate(message)
```

- [ ] **Step 4: Run tests to verify GREEN for daily report**

Run the Task 3 test command.

Expected: PASS, with the existing FastAPI/Starlette warning acceptable if unchanged from baseline.

---

### Task 4: Truncation and QA copy cleanup

**Files:**
- Modify: `tests/test_storage_reporting_publish.py`
- Modify: `src/polysignal_lab/publish/telegram_qa.py` only if adopting compact QA copy
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_telegram_validation.py -q`

**Interfaces:**
- Consumes: existing `MessageFormatter._truncate` and `DEFAULT_MESSAGE`.
- Produces: preserved truncation behavior and no stale QA disclaimer if the QA message is adjusted.

- [ ] **Step 1: Verify truncation test expects new prefix and old suffix**

Update `test_formatter_truncates_long_signal_message` if needed so it asserts:

```python
assert message.startswith("<b>🟢 ")
assert message.endswith("\n[truncated for Telegram]")
assert len(message) <= 240
```

- [ ] **Step 2: Optionally shorten QA default message**

If `DEFAULT_MESSAGE` is changed, use:

```python
DEFAULT_MESSAGE = "<b>PolySignal Lab</b>\nTelegram QA send · Mode: Paper"
```

Do not change `TelegramPublisher` payload behavior.

- [ ] **Step 3: Run tests to verify GREEN for truncation and publisher validation**

Run the Task 4 test command.

Expected: PASS, with no new warnings beyond baseline.

---

### Task 5: Final verification and commit

**Files:**
- Review changed formatter/test/QA files only.
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_reporting.py tests/test_telegram_validation.py -q`

**Interfaces:**
- Consumes: all completed tasks.
- Produces: committed implementation on `feat/telegram-notification-templates`.

- [ ] **Step 1: Run targeted regression suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py tests/test_reporting.py tests/test_telegram_validation.py -q
```

Expected: PASS.

- [ ] **Step 2: Commit implementation**

Run:

```bash
git add src/polysignal_lab/signal_layer/formatter.py src/polysignal_lab/publish/telegram_qa.py tests/test_storage_reporting_publish.py tests/test_reporting.py docs/superpowers/plans/2026-06-23-telegram-notification-template-implementation.md
git commit -m "feat: compact telegram notification templates"
```

Expected: commit succeeds on `feat/telegram-notification-templates`.
