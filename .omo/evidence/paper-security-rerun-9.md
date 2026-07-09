# Paper Security Rerun 9

verdict: PASS
severity: NONE
recommendation: APPROVE
reportPath: .omo/evidence/paper-security-rerun-9.md
notepadPath: /tmp/ulw-20260709-073517.EXDhbg.md

## Original Intent

Security-only read-only rerun after the zero-money fix. Re-audit prior blockers from security rerun 7 and code rerun 7: live settlement must fail closed for missing, non-finite, zero, and negative/invalid money fields; Nautilus projection must not convert missing money into zero durable settlement data; malformed JSON in `paper_trade_results`, `system_events`, `daily_reports`, and same-key idempotent inserts must fail closed.

## Desired Outcome

The user receives this report with a PASS/FAIL verdict, severity, blockers, and evidence from current source plus the required `.omo/ulw-loop/evidence/paper-post-zero-money-*` and `.omo/ulw-loop/evidence/paper-post-security-fix-*` artifacts. No production or test files are edited.

## User Outcome Review

PASS. Current source and fresh probes show the rerun-7 and code-rerun-7 blockers are resolved. Missing, non-finite, zero, and negative settlement money all fail closed before persistence. Missing/unparseable Nautilus position money remains `None` in projection output instead of becoming zero settlement data. Malformed JSON in the named storage surfaces is skipped or returned as a typed store error.

## Blockers

None.

## Prior Blocker Recheck

| Prior blocker | Current result | Evidence |
| --- | --- | --- |
| Live settlement missing money fabricated `0.0` trade result | PASS | `src/polysignal_lab/app/_settlement_check.py:189-209` rejects missing, non-finite, zero, and negative `quantity`/`entry_price`/`stake_usdc`; `:131-139` skips storage when result is `None`. |
| Projection layer normalized missing Nautilus money to zero | PASS | `src/polysignal_lab/nautilus_runtime/projections.py:77-86` derives position money with optional parsing; `:186-222` returns `None` for missing, non-finite, or unparseable money. |
| Malformed `paper_trade_results` payloads crash or leak | PASS | `src/polysignal_lab/storage/sqlite_store.py:400-408` catches malformed JSON and invalid parsed trade rows. |
| Malformed `system_events` and `daily_reports` crash restore/report surfaces | PASS | `src/polysignal_lab/storage/sqlite_store.py:409-417` skips malformed payloads; restore surfaces route through `:433-470`; latest system event catches malformed JSON at `:379-394`. |
| Same-key idempotent insert with malformed existing payload crashes as raw JSONDecodeError | PASS | `src/polysignal_lab/storage/sqlite_store.py:496-520` raises `MalformedSQLitePayloadError`. |
| Deletion-only settlement test from code rerun 7 | PASS | `tests/test_settlement.py:35-155` now contains behavior tests; no `module_is_removed`/`Path(...).exists()` deletion-only test remains in the reviewed settlement tests. |

## Fresh Evidence

Focused pytest rerun:

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_settlement.py \
  tests/test_scheduler_settlement_resolution.py \
  tests/test_nautilus_projections.py \
  tests/test_storage_restore.py

.............................................                            [100%]
```

Manual adversarial probe:

```text
settlement_missing_quantity=None
settlement_missing_avg_entry_price=None
settlement_missing_stake_usdc=None
settlement_nan_quantity=None
settlement_inf_avg_entry_price=None
settlement_zero_quantity=None
settlement_zero_avg_entry_price=None
settlement_zero_stake_usdc=None
settlement_negative_quantity=None
settlement_negative_avg_entry_price=None
settlement_negative_stake_usdc=None
project_position_missing_money={... 'quantity': None, 'avg_entry_price': None, 'stake_usdc': None, ...}
project_position_unparseable_money={... 'quantity': None, 'avg_entry_price': None, 'stake_usdc': None, ...}
paper_trade_results=[]
system_events=[]; open_positions=[]; latest=None
daily_reports=[]; leaderboard=[]
same_key_idempotent=MalformedSQLitePayloadError:malformed system_events.payload_json for event_id=evt-same
```

Targeted type check:

```text
PYTHONDONTWRITEBYTECODE=1 uv run basedpyright \
  src/polysignal_lab/app/_settlement_check.py \
  src/polysignal_lab/nautilus_runtime/projections.py \
  src/polysignal_lab/storage/sqlite_store.py \
  src/polysignal_lab/domain/paper_result.py \
  tests/test_settlement.py \
  tests/test_scheduler_settlement_resolution.py \
  tests/test_nautilus_projections.py \
  tests/test_storage_restore.py

0 errors, 412 warnings, 0 notes
```

## Required Artifact Evidence

- `.omo/ulw-loop/evidence/paper-post-zero-money-focused-pytest.txt`: `48 passed`.
- `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt`: `settlement_zero_money None`; projected missing money fields are `None`; malformed system/daily storage returns empty/`None`; same-key malformed payload raises `MalformedSQLitePayloadError`.
- `.omo/ulw-loop/evidence/paper-post-zero-money-full-pytest.txt`: full pytest pass.
- `.omo/ulw-loop/evidence/paper-post-zero-money-basedpyright.txt`: 0 errors.
- `.omo/ulw-loop/evidence/paper-post-zero-money-compileall.txt`: pass.
- `.omo/ulw-loop/evidence/paper-post-zero-money-diff-check.txt`: pass.
- `.omo/ulw-loop/evidence/paper-post-zero-money-refs-check.txt`: pass.
- `.omo/ulw-loop/evidence/paper-post-security-fix-focused-pytest.txt`: earlier focused pass; post-zero summary supersedes it with 48 passed.
- `.omo/ulw-loop/evidence/paper-post-security-fix-full-pytest.txt`: full pytest pass.
- `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt`: focused/full/type/manual/compile/diff/refs pass after zero-money fix.

## Slop And Skill-Perspective Check

- `remove-ai-slops`: direct overfit/slop pass over the security slice found no unresolved blocker. The current tests are behavior-oriented: they assert no settlement result and no persistence call for invalid money, `None` projection money for missing Nautilus attributes, empty restore results for malformed JSON, and a typed idempotence error. They are not deletion-only, tautological, or implementation-mirroring in the reviewed security paths.
- `programming`: direct review confirms the boundary now parses invalid money to `None`/rejection before settlement storage. Remaining `basedpyright` warnings are existing typed debt, not current security blockers.
- Minimality: no new dependency or speculative abstraction is needed for this security outcome. The fix sits at shared settlement/projection/storage boundaries.

## Evidence Gaps

No blocking evidence gaps for the requested security rerun. Negative money is covered by the fresh manual probe and by the same `<= 0.0` source guard as the zero-money pytest cases; it is not separately parametrized in pytest.

<verdict>PASS</verdict>
