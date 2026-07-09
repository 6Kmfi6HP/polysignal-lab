codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-security-rerun-7.md

# Paper Security Rerun 7

Read-only security review of the current Nautilus paper/domain/storage refactor.

## Skill-Perspective Check

- `remove-ai-slops`: ran by loading the skill and applying its overfit/slop review criteria to tests and production code. Violations found: the malformed JSON test/fix is overfit to `paper_trade_results` while the same restore surface still crashes for `system_events` and `daily_reports`; live settlement lacks an adversarial missing-money-payload test.
- `programming`: ran by loading the skill, Python reference, and logging reference. Violations found: production code still passes untyped payloads through settlement/storage boundaries and defaults missing numeric settlement fields to `0.0`; broad publish exception handling is not a blocker here because it runs after durable persistence and redacts the stored error text.
- Ponytail/minimality lens: no new dependency issue found; blockers are smaller to fix at the shared storage/settlement boundaries than per caller.

## Evidence Reviewed

- Current diff: 68 tracked files changed, 3351 insertions, 1897 deletions.
- Requested post-malformed artifacts:
  - `.omo/ulw-loop/evidence/paper-post-malformed-verification-summary.txt`: focused pytest pass, system Python focused pytest pass, basedpyright 0 errors, compileall pass, diff_check pass, refs_check pass.
  - `.omo/ulw-loop/evidence/paper-post-malformed-focused-pytest.txt`: 29 focused tests passed.
  - `.omo/ulw-loop/evidence/paper-post-malformed-full-pytest.txt`: full pytest passed.
  - `.omo/ulw-loop/evidence/paper-post-malformed-basedpyright.txt`: 0 errors, but many warnings remain in touched settlement/repair/Telegram files.
  - `.omo/ulw-loop/evidence/paper-post-malformed-refs-check.txt`: empty.
- Fresh commands run:
  - `git diff --check`: pass.
  - Focused 10-test rerun for settlement side/timestamp, malformed paper trade payload, repair missing fields, publish invalid payload, Telegram missing side: `10 passed`.
  - Protected refs check: `git status --short -- refs @refs docs/nautilus_reference` and `git diff --name-only -- refs @refs docs/nautilus_reference` produced no output.
  - Fresh direct probe reproduced the blockers below.

## Findings By Severity

### CRITICAL

None.

### HIGH

1. Live settlement can fabricate and persist a valid-looking trade result from missing numeric payload data.

`src/polysignal_lab/app/_settlement_check.py:187` computes `quantity` from `shares` or `quantity` and falls back to `0.0`; `src/polysignal_lab/app/_settlement_check.py:192` does the same for `entry_price`; `src/polysignal_lab/app/_settlement_check.py:197` derives missing `stake_usdc` as `quantity * entry_price`. The function then returns a normal result payload at `src/polysignal_lab/app/_settlement_check.py:228` through `src/polysignal_lab/app/_settlement_check.py:252`.

Fresh probe result:

```text
live_missing_money_results_len=1
live_missing_money_result_fields={'entry_price': 0.0, 'shares': 0.0, 'stake_usdc': 0.0, 'settlement_value': 0.0, 'pnl_usdc': 0.0, 'result': 'WIN'}
live_missing_money_persisted_len=1
```

This violates the security question "Does any path fabricate valid-looking trade results from missing/invalid side/timestamp/payload data?" Side and timestamp now fail closed, but missing monetary payload still becomes a persisted `WIN` row. `scripts/repair_settlement_results.py:198` through `scripts/repair_settlement_results.py:206` correctly fail-closes the same missing money fields, so the live settlement path is the inconsistent unsafe path.

2. Malformed persisted JSON still crashes user-facing restore/report surfaces and same-id idempotent writes outside the narrow `paper_trade_results` query path.

`src/polysignal_lab/storage/sqlite_store.py:381` through `src/polysignal_lab/storage/sqlite_store.py:386` catches malformed JSON only when `table == "paper_trade_results"`; every other table still directly `json.loads(...)` each payload. `restore_open_positions()` routes through `system_events` at `src/polysignal_lab/storage/sqlite_store.py:410` through `src/polysignal_lab/storage/sqlite_store.py:431`. Dashboard `/api/positions` also calls `store.query_json("system_events", ...)` at `src/polysignal_lab/dashboard/app.py:469` through `src/polysignal_lab/dashboard/app.py:490`; Telegram positions and status call `restore_open_positions()` at `src/polysignal_lab/publish/telegram_bot.py:337` and `src/polysignal_lab/publish/telegram_bot.py:620`. Daily report restore also goes through the unguarded path at `src/polysignal_lab/storage/sqlite_store.py:442` through `src/polysignal_lab/storage/sqlite_store.py:447`, used by Telegram daily at `src/polysignal_lab/publish/telegram_bot.py:418` and dashboard report/leaderboard surfaces at `src/polysignal_lab/dashboard/app.py:415` and `src/polysignal_lab/dashboard/app.py:499`.

Fresh probe result:

```text
restore_open_positions_malformed_system_events=EXC:JSONDecodeError
dashboard_positions_query_malformed_system_events=EXC:JSONDecodeError
restore_daily_reports_malformed_json=EXC:JSONDecodeError
paper_trade_results_malformed_json=OK:[]
insert_same_id_existing_malformed_payload=EXC:JSONDecodeError
```

The idempotence path also calls `json.loads(existing["payload_json"])` without handling malformed existing storage at `src/polysignal_lab/storage/sqlite_store.py:486` through `src/polysignal_lab/storage/sqlite_store.py:489`. It does not bypass idempotence into a forged insert, but it does crash instead of fail-closing or surfacing a typed duplicate/corruption error.

### MEDIUM

None.

### LOW

- `src/polysignal_lab/app/_settlement_check.py:318` catches broad `Exception` around Telegram publish. I am not treating this as a blocker because persistence already happened, the stored audit event redacts `str(exc)` at `src/polysignal_lab/app/_settlement_check.py:337`, and the catch protects settlement from Telegram availability failures. It remains maintenance debt under the programming/remove-ai-slops perspectives.
- General docs have unrelated untracked files: `docs/architecture-nautilus-alignment.md` and `docs/superpowers/plans/2026-07-09-architecture-boundary-cleanup.md`. Protected refs paths checked for this review, `refs`, `@refs`, and `docs/nautilus_reference`, are untouched.

## Security Questions

- Fabricated valid-looking trade results from missing/invalid side/timestamp/payload data: FAIL. Side/timestamp now fail closed, but live missing numeric payload data persists a normal `WIN` result with zero monetary fields.
- Malformed persisted JSON or invalid payload disclosure/crash/idempotence bypass: FAIL. `paper_trade_results` malformed JSON is skipped, but malformed `system_events` and `daily_reports` crash restore/report surfaces, and same-id malformed existing payload crashes idempotence comparison.
- Broad exception handling/logging/repair changes introducing hidden data loss, secret leakage, unsafe writes: WATCH. No direct secret leak or unsafe unparameterized SQL write found. Repair apply requires backup through config validation; backfill/wallet create backups before mutation. Publish error audit uses redaction. Broad catch remains low maintenance risk.
- Protected refs/docs untouched: PASS for `refs`, `@refs`, and `docs/nautilus_reference`; unrelated untracked docs exist outside those protected paths.

## Test Relevance

The focused tests are not deletion-only and do exercise meaningful behavior for side/timestamp, repair, publish invalid payload, and `paper_trade_results` malformed JSON. They are still insufficient for approval because they mirror the narrow fix scope:

- No adversarial live settlement test proves missing `quantity`/`entry_price`/`stake_usdc` fails closed.
- No malformed JSON test covers `system_events` or `daily_reports`, even though those tables back user-facing restore/report surfaces through the same `query_json()` helper.

## Blockers

- Fix live settlement so missing/invalid numeric payload fields cannot become a persisted paper trade result; add a focused adversarial test for that path.
- Fix malformed JSON handling for user-facing restore/report surfaces and idempotence comparison, or fail closed with a typed corruption result; add tests for `system_events`, `daily_reports`, and same-id malformed existing payload behavior.

<verdict>FAIL</verdict>
