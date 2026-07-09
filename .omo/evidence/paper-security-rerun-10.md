# Paper Security Rerun 10

verdict: PASS
severity: NONE
recommendation: APPROVE
codeQualityStatus: WATCH
reportPath: .omo/evidence/paper-security-rerun-10.md
notepadPath: /tmp/ulw-20260709-084159.2ChQs7.md
blockers: []

## Scope

Narrow post-R10 security/data-safety rerun for changed reporting, settlement,
projection, storage, and orderbook parser paths. Block criteria were limited to
exploitable injection, secret leakage, unsafe malformed JSON behavior, and data
corruption. R10 direct Nautilus cache calls were treated as security-neutral
unless they introduced exploitable failure.

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied as a review lens. No deletion-only tests,
  tautological tests, tests that only verify a requested removal, or production
  parsing/normalization drift that creates a security/data-safety blocker were
  found in the reviewed slice.
- `programming`: loaded with the Python reference and applied as a review lens.
  The reviewed code still has broad type/size debt visible in basedpyright and
  LOC checks, so `codeQualityStatus` is WATCH. Those items are not exploitable
  security/data-safety blockers for this narrow rerun.

## Evidence Inspected

- Prior approval: `.omo/evidence/paper-security-rerun-9.md` was PASS/NONE.
- Post-R10 evidence:
  - `.omo/ulw-loop/evidence/paper-post-r10-rg.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-focused-pytest.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-full-pytest.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-basedpyright.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-diff-stat.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-git-status.txt`
  - `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt`

Fresh focused verification:

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_settlement.py \
  tests/test_scheduler_settlement_resolution.py \
  tests/test_storage_restore.py \
  tests/test_orderbook_snapshot.py \
  tests/test_polymarket_clob_rest.py \
  tests/test_nautilus_reporting_cache_source.py

.........................................................                [100%]
```

Post-R10 evidence showed full pytest green, basedpyright 0 errors with warnings,
and direct cache calls only at `src/polysignal_lab/app/scheduler_reporting.py:296`
and `src/polysignal_lab/app/scheduler_reporting.py:315`.

Reviewer gate note: `multi_agent_v1.spawn_agent` was not available in this
harness after tool discovery, so no child reviewer approval was obtained.

## Findings by Severity

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

- Non-blocking maintainability residue: reviewed production files still contain
  type strictness and size debt under the `programming` lens, including
  `Any`/`cast` warnings in the post-R10 basedpyright artifacts and files over
  250 pure LOC. This is not a security blocker under the requested criteria.

## Security Checks

### Settlement and projection money

PASS. Settlement still fails closed before persistence for missing, non-finite,
zero, or negative money fields. The shared guard is in
`src/polysignal_lab/app/_settlement_check.py:189-209`; storage only happens after
the result is non-None at `src/polysignal_lab/app/_settlement_check.py:131-139`
and `src/polysignal_lab/app/_settlement_check.py:279-285`.

PASS. Nautilus position projection preserves missing/unparseable money as
`None` and derives `stake_usdc` only from finite parsed quantity and average
entry price at `src/polysignal_lab/nautilus_runtime/projections.py:77-86` and
`src/polysignal_lab/nautilus_runtime/projections.py:186-222`.

### Storage malformed JSON and corruption

PASS. `paper_trade_results` insert/restore paths fail closed through typed
parsing at `src/polysignal_lab/storage/sqlite_store.py:326-335` and
`src/polysignal_lab/storage/sqlite_store.py:400-408`.

PASS. Malformed `system_events` and `daily_reports` payloads are skipped on the
reviewed restore/query surfaces at `src/polysignal_lab/storage/sqlite_store.py:379-417`.
Same-key idempotent insert with malformed existing JSON raises typed
`MalformedSQLitePayloadError` at `src/polysignal_lab/storage/sqlite_store.py:496-520`.

### SQL injection

PASS. Reviewed SQL paths bind user-controlled values through parameters:
`src/polysignal_lab/app/scheduler_reporting.py:175-183`,
`src/polysignal_lab/app/scheduler_reporting.py:211-216`,
`src/polysignal_lab/app/scheduler_reporting.py:357-364`,
`src/polysignal_lab/app/scheduler_reporting.py:419-424`, and
`src/polysignal_lab/app/scheduler_reporting.py:526-528`. Dynamic table names are
constrained by `ALLOWED_TABLES` at `src/polysignal_lab/storage/sqlite_store.py:178-189`
and `src/polysignal_lab/storage/sqlite_schema.py:155-182`.

### Orderbook parser and malformed JSON

PASS. Orderbook payload shape is validated at
`src/polysignal_lab/data/orderbook_payload.py:65-69`; missing token IDs fail
closed at `src/polysignal_lab/data/orderbook_payload.py:93-97`; invalid,
non-positive, or non-finite levels are ignored at
`src/polysignal_lab/data/orderbook_payload.py:72-90`. Websocket malformed JSON
is counted and ignored at `src/polysignal_lab/data/polymarket_clob_ws.py:117-124`.

### Secret leakage

PASS. Scoped secret scan found no credential logging or public constructor
surface for CLOB credentials. `tests/test_polymarket_clob_rest.py:29-39` pins
that SDK credentials/private keys are not exposed. Settlement publish failure
logging redacts exception text before durable audit at
`src/polysignal_lab/app/_settlement_check.py:319-348`.

## Verdict

PASS. Severity NONE. No exploitable injection, secret leakage, unsafe malformed
JSON behavior, or data corruption blocker was found in the post-R10 scoped
paths. R10 direct cache calls are security-neutral in the current code and
evidence.
