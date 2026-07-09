# Paper Security Rerun 8

recommendation: REJECT
verdict: FAIL
severity: HIGH
reportPath: .omo/evidence/paper-security-rerun-8.md
notepadPath: /tmp/ulw-20260709-065419.V6C1cp.md

## Original Intent

Read-only security rerun for the current Nautilus paper/domain/storage refactor. Re-audit rerun-7 blockers: fail-closed live settlement money handling, and malformed persisted JSON resilience for `paper_trade_results`, `system_events`, `daily_reports`, plus same-key idempotence comparison.

## Desired Outcome

The user should receive a security-only PASS/FAIL report grounded in current source, required evidence artifacts, and fresh direct probes. No production or test files should be edited.

## User Outcome Review

The malformed JSON blocker is fixed. The explicit missing and non-finite settlement tests now pass. I still cannot approve the security outcome because zero-valued settlement money can still become a valid-looking WIN result, and the projection layer still normalizes missing/unparseable numeric position attributes to `0.0`.

## Blockers

### HIGH: zero-valued settlement money still produces a valid-looking result

`src/polysignal_lab/app/_settlement_check.py:189-206` rejects `None` and non-finite money fields, but accepts `0.0` for quantity, entry price, and stake. The result builder then returns a normal settled row at `src/polysignal_lab/app/_settlement_check.py:235-260`, including `result='WIN'`, zero money fields, and `roi=0.0`.

This matters because `src/polysignal_lab/nautilus_runtime/projections.py:79-87` gets `signed_qty` and `avg_px_open` through `_float_attr()`, and `_to_float()` returns `0.0` on missing/unparseable values at `src/polysignal_lab/nautilus_runtime/projections.py:147-177`. That leaves a missing-money bypass if a projected position reaches settlement with market identity populated.

Fresh direct probe:

```text
_paper_trade_result_from_projection(... quantity=0.0, avg_entry_price=0.0, stake_usdc=0.0 ...)
=> {'entry_price': 0.0, 'shares': 0.0, 'stake_usdc': 0.0, 'settlement_value': 0.0, 'pnl_usdc': 0.0, 'result': 'WIN'}
```

The raw missing-attribute probe through `check_settlements()` did not persist only because `project_position()` also omits `market_id`; that does not make the settlement row builder fail-closed.

## Stale Blocker Recheck

- Missing/non-finite live settlement fields: PARTIAL. Current tests and a fresh probe show absent/NaN/inf fields return no result and do not call persistence. The zero-money bypass above remains unresolved.
- Malformed `paper_trade_results`: PASS. `SQLiteStore.query_json()` catches `json.JSONDecodeError` and `InvalidPaperTradeResultRow` for `paper_trade_results` at `src/polysignal_lab/storage/sqlite_store.py:400-408`.
- Malformed `system_events` and `daily_reports`: PASS. `SQLiteStore.query_json()` skips malformed payloads for both tables at `src/polysignal_lab/storage/sqlite_store.py:409-416`; restore/report surfaces route through this helper at `src/polysignal_lab/storage/sqlite_store.py:433-470`.
- Same-key idempotence comparison: PASS. `_insert_idempotent()` converts malformed existing payload JSON into `MalformedSQLitePayloadError` at `src/polysignal_lab/storage/sqlite_store.py:510-517`, rather than crashing with `JSONDecodeError` or bypassing duplicate handling.

## Evidence

Checked artifacts:

- `.omo/evidence/paper-security-rerun-7.md`
- `.omo/evidence/paper-code-review-rerun-7.md`
- `.omo/ulw-loop/evidence/paper-security-fix-manual-qa.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-system-python-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-refs-check.txt`

Fresh commands:

```text
uv run pytest tests/test_settlement.py tests/test_scheduler_settlement_resolution.py -k 'missing_money or missing_numeric_money' -q
=> 8 passed

uv run pytest tests/test_storage_restore.py -k 'malformed or incomplete or invalid_position or without_side or malformed_existing_payload' -q
=> 9 passed

uv run pytest tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_storage_restore.py -q
=> 36 passed

uv run pytest -q
=> full suite passed; 2 NautilusTrader pandas DeprecationWarnings

git diff --check
=> pass

git status --short -- refs @refs docs/nautilus_reference
git diff --name-only -- refs @refs docs/nautilus_reference
=> no output
```

Fresh malformed JSON probe:

```text
paper_trade_results []
system_events [] [] None
daily_reports [] []
same_key_idempotence=typed_error MalformedSQLitePayloadError
```

## Slop And Skill-Perspective Check

- `remove-ai-slops`: the new malformed JSON and missing/non-finite money tests are behavior tests against persistence/restore/settlement outcomes, not tautological removal checks. They still miss the zero-money bypass. A pre-existing deletion-only test remains at `tests/test_settlement.py:35-38`, but it was not introduced by the inspected security-fix diff.
- `programming`: targeted `basedpyright` returned `0 errors, 412 warnings`. The security blocker is not typecheck failure; it is boundary parsing that treats zero-valued economic fields as valid and projection parsing that converts unknown values to `0.0`.

## Evidence Gaps

- No regression test covers zero-valued settlement money (`quantity=0.0`, `avg_entry_price=0.0`, `stake_usdc=0.0`) failing closed.
- No projection test covers missing/unparseable Nautilus position money attributes staying unknown instead of becoming `0.0`.

<verdict>FAIL</verdict>
