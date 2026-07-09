recommendation: REJECT
verdict: FAIL
confidence: high
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-goal-verification-rerun-8.md
notepadPath: /tmp/ulw-20260709-073624.b4LK8r.md

# Paper Goal Verification Rerun 8

## originalIntent

Verify the current ULW completion state after the zero-money fix, without editing production or test files:

- G001: OrderBook safe slice is complete.
- G002/G003: paper/converter/domain/schema/R10 completion is real after the paper model/table/converter migration and zero-money fix.
- G004-G014: duplicate auto-split goals are legitimately blocked or superseded.
- Previous rerun-7 rejects must be treated as stale only if current source and current post-zero evidence support that conclusion.

## desiredOutcome

A user-visible PASS/FAIL verification report grounded in current source, current ULW state, current evidence, direct slop/programming review, and fresh read-only checks.

## constraints

- Scope: `/home/debian/polysignal-lab`.
- Required inputs read: `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`, `goals.json`, `ledger.jsonl`, `.omo/ulw-loop/evidence/paper-post-zero-money-*`, `.omo/evidence/paper-context-rerun-8.md`, `.omo/evidence/paper-qa-rerun-7.md`, current source, and relevant stale rerun artifacts.
- Read-only for production and test files; this report is the only repository file written by this rerun.
- Protected refs and `docs/nautilus_reference` must remain untouched.

## userOutcomeReview

The current source and post-zero-money evidence now support the substantive implementation outcome: the OrderBook safe slice is complete, the backend paper/domain/schema/R10 cleanup is complete for the stated scope, the zero-money settlement blocker is fixed, and G004-G014 are duplicate/superseded placeholders rather than unfinished implementation work.

I still cannot approve the final package because the artifact set is incomplete for a gate approval. The latest paper code-review report with explicit `remove-ai-slops` and `programming` coverage is `.omo/evidence/paper-code-review-rerun-7.md`, which predates the zero-money green evidence and is a FAIL report. `.omo/evidence/paper-security-rerun-8.md` also predates the green zero-money proof and is a FAIL report. The post-zero evidence contains tests, manual QA, compile/type/diff/refs checks, but no current code-review/security approval artifact. Under the gate criteria, direct verification does not replace the missing review report coverage.

## goalBreakdown

### G001 OrderBook Safe Slice

Status: PASS.

Evidence:
- `goals.json` marks G001 complete and records the safe slice: domain `from_polymarket` removed, data/app parser boundary implemented, focused pytest 32 passed, regression 101 passed, basedpyright 0 errors, final gate approved.
- `src/polysignal_lab/domain/orderbook.py:29-81` contains only the simplified `OrderBook` container and derived metrics; no `from_polymarket` parser remains.
- `src/polysignal_lab/data/orderbook_payload.py:42-101` owns public payload parsing and rejects non-object or missing-token payloads through `InvalidOrderBookPayload`.
- `.omo/ulw-loop/evidence/scope-decision.txt` documents the safe slice and explicitly defers full custom OrderBook/state-registry removal as long-term/high-impact work.

### G002/G003 Paper / Converter / Domain / Schema / R10

Status: FUNCTIONAL PASS, artifact-gate FAIL.

Evidence supporting completion:
- `goals.json` marks G002 and G003 complete with paper/converter/domain/schema/R10 search evidence and full pytest evidence.
- Current backend search found no active `class PaperOrder`, `class PaperFill`, `class PaperPosition`, `class PaperTradeResult`, `order_converter`, `position_converter`, or `CREATE/INSERT` paths for `paper_orders`, `paper_fills`, or `paper_positions` under `src`/`tests`.
- `src/polysignal_lab/storage/sqlite_schema.py:70-98` keeps only `paper_trade_results` and `paper_wallet_snapshots` as app-local audit/projection tables, with `COUNT_TABLES` entries at lines 181-192.
- `src/polysignal_lab/app/scheduler_reporting.py` R10 evidence in `.omo/ulw-loop/evidence/node-r10-rg.txt` shows direct `nautilus_cache.account()` and `nautilus_cache.positions()` calls.
- `src/polysignal_lab/app/_settlement_check.py:189-209` now rejects missing, non-finite, zero, or negative `quantity`, `entry_price`, and `stake` before a paper result can be built.
- `src/polysignal_lab/nautilus_runtime/projections.py:77-98` now leaves missing position money unknown (`None`) instead of fabricating zero money.
- `tests/test_settlement.py:133-154`, `tests/test_scheduler_settlement_resolution.py:336-403`, and `tests/test_nautilus_projections.py:140-151` cover zero/missing money and missing projection money behavior.
- Fresh direct probe: valid row returns `WIN`; `zero_quantity`, `zero_entry`, `zero_stake`, and `missing_stake` all return `None`; projected position with missing money returns `quantity=None`, `avg_entry_price=None`, `stake_usdc=None`.
- Fresh focused pytest: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_nautilus_projections.py tests/test_storage_restore.py` -> `45 passed`.
- Post-zero artifacts: `paper-zero-money-red.txt` captured the two intended RED failures, `paper-zero-money-green.txt` shows the direct green, `paper-zero-money-scheduler-green.txt` shows scheduler green, `paper-post-zero-money-focused-pytest.txt` shows 48 passed, `paper-post-zero-money-full-pytest.txt` shows full suite green, `paper-post-zero-money-manual-qa.txt` shows `settlement_zero_money None` and missing projected money as `None`.

Blocking artifact gap:
- No current post-zero-money code-review report exists. The only named current code-review artifact is stale and failing.

### G004-G014 Duplicate Auto-Splits

Status: LEGITIMATELY BLOCKED/SUPERSEDED.

Evidence:
- `goals.json` marks G004-G014 `blocked`.
- Each G004-G014 entry uses the same steering rationale: "Collapse invalid auto-generated URL/constraint fragments into completed concrete stories."
- The blocked items are duplicate fragments of constraints or criteria already covered by G001/G002/G003 evidence, not independent remaining implementation tasks.

## directSlopAndProgrammingPass

- `remove-ai-slops` direct pass: the stale deletion-only test flagged in rerun 7 has been removed from `tests/test_settlement.py`; the zero-money and missing-money tests exercise observable settlement/projection behavior and are not tautological removal checks. I did not find a new overfit/implementation-mirroring test in the zero-money diff.
- `programming` direct pass: the fix is at the shared settlement/projection boundary, not per-caller guards; it is behaviorally fail-closed for missing, non-finite, zero, or negative economic inputs. `basedpyright` still reports warnings (`0 errors, 176 warnings`) in dynamic scheduler/test surfaces, but the fresh scoped command has no errors.
- Report coverage check: FAIL. No post-zero code-review report repeats this skill-perspective check or approves the current final diff.

## blockers

1. HIGH: Missing current code-review approval after the zero-money fix.
   - Latest inspected code-review artifact: `.omo/evidence/paper-code-review-rerun-7.md`.
   - It is a FAIL report and its timestamp (`2026-07-09 07:17:01 +0200`) predates `paper-zero-money-green.txt` (`2026-07-09 07:27:42 +0200`) and `paper-post-zero-money-full-pytest.txt` (`2026-07-09 07:31:04 +0200`).
   - The gate requires explicit `remove-ai-slops` and `programming` report coverage; direct reviewer checks do not replace that missing artifact.

2. HIGH: Stale failing security artifact remains unresolved at the artifact level.
   - `.omo/evidence/paper-security-rerun-8.md` is a FAIL report and predates the green zero-money proof.
   - Current source/direct probes show the zero-money issue is fixed, but there is no post-zero security rerun artifact overturning the stale FAIL report.

## freshChecksRun

- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_nautilus_projections.py tests/test_storage_restore.py` -> `45 passed`.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/nautilus_runtime/projections.py tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_nautilus_projections.py` -> `0 errors, 176 warnings, 0 notes`.
- `PYTHONDONTWRITEBYTECODE=1 python -m compileall -q` on inspected settlement/projection/orderbook/storage/paper-result files -> pass.
- `git diff --check` -> pass.
- Direct probe -> valid settlement row builds; zero/missing money returns `None`; missing projected money remains `None`.
- `rg` source/evidence searches for Paper* models/tables/converters, OrderBook parser, and R10 cache access.

## checkedArtifactPaths

- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/ledger.jsonl`
- `.omo/ulw-loop/evidence/scope-decision.txt`
- `.omo/ulw-loop/evidence/orderbook-from-polymarket-rg.txt`
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt`
- `.omo/ulw-loop/evidence/orderbook-surface.txt`
- `.omo/ulw-loop/evidence/orderbook-regression.txt`
- `.omo/ulw-loop/evidence/orderbook-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-models-rg.txt`
- `.omo/ulw-loop/evidence/paper-schema-rg.txt`
- `.omo/ulw-loop/evidence/node-r10-rg.txt`
- `.omo/ulw-loop/evidence/paper-settlement-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-zero-money-red.txt`
- `.omo/ulw-loop/evidence/paper-zero-money-green.txt`
- `.omo/ulw-loop/evidence/paper-zero-money-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-zero-money-scheduler-green.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-system-python-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-compileall.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-refs-check.txt`
- `.omo/evidence/paper-context-rerun-8.md`
- `.omo/evidence/paper-qa-rerun-7.md`
- `.omo/evidence/paper-code-review-rerun-7.md`
- `.omo/evidence/paper-security-rerun-8.md`
- `.omo/evidence/paper-goal-verification-rerun-7.md`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/nautilus_runtime/projections.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/domain/paper_result.py`
- `tests/test_settlement.py`
- `tests/test_scheduler_settlement_resolution.py`
- `tests/test_nautilus_projections.py`
- `tests/test_storage_restore.py`

## exactEvidenceGaps

- Missing post-zero-money code-review report with explicit `remove-ai-slops` and `programming` coverage for the current final diff.
- Missing post-zero-money security rerun report that supersedes stale `.omo/evidence/paper-security-rerun-8.md`.
- No consolidated post-zero reviewer approval artifact exists; the current proof bundle is tests/manual QA/direct verification plus stale failing review/security reports.
- Frontend still has `PaperOrder` / `PaperPosition` / `PaperTradeResult` API types and paper-trading UI fixtures. `.omo/evidence/paper-context-rerun-8.md` classifies this as a separate SPA contract, not a backend domain/schema blocker; if the intended scope is all user-facing paper surfaces, this needs separate verification.

## finalRecommendation

REJECT / FAIL. Functionally, G001 and G002/G003 now appear complete after the zero-money fix and G004-G014 are legitimately blocked/superseded. The final gate still fails because the artifact set lacks current post-zero code-review/security approval and still contains stale failing review artifacts.

<verdict>FAIL</verdict>
