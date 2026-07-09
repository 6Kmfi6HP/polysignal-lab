recommendation: REJECT
verdict: FAIL
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-goal-verification-rerun-11.md
notepadPath: /tmp/ulw-20260709-090055.TSacWi.md

# Paper Goal Verification Rerun 11

## originalIntent

Rerun the narrow final gate after the reporting-cache protocol fix. Approve only if the current state satisfies G001 OrderBook safe slice, G002/G003 Paper/R10 refactor, app-local audit table retention, refs protection, no commit, direct R10 Nautilus cache calls inside the helper, and a non-crashing boundary for non-protocol cache objects.

## desiredOutcome

Return PASS only if no blockers remain and the current artifacts, source, tests, QA, code review, and direct slop/programming pass all support completion.

## recommendation

REJECT.

## blockers

1. `src/polysignal_lab/app/scheduler_reporting.py:276-297` still crashes for adversarial non-protocol cache objects whose `account` or `positions` attributes exist but are not callable.

   Fresh probe:

   ```text
   PYTHONDONTWRITEBYTECODE=1 uv run python - <<'PY'
   from types import SimpleNamespace
   from polysignal_lab.app.scheduler_reporting import _report_equity_inputs
   settings = SimpleNamespace(paper_trading=SimpleNamespace(starting_balance_usdc=1000.0))
   invalid_caches = [
       SimpleNamespace(),
       SimpleNamespace(account=123, positions=lambda: []),
       SimpleNamespace(account=lambda: None, positions=[]),
   ]
   for cache in invalid_caches:
       scheduler = SimpleNamespace(settings=settings, nautilus_cache=cache)
       assert _report_equity_inputs(scheduler) == (1000.0, 1000.0, 0)
   PY
   ```

   Result:

   ```text
   TypeError: 'int' object is not callable
   ```

   Root cause: `@runtime_checkable Protocol` confirms attribute presence, not callable method compatibility, so malformed cache objects can still pass the boundary and crash inside `_report_equity_inputs_from_nautilus_cache()`.

2. The rerun-10 code review and goal reports are unsupported on the exact protocol boundary criterion. `.omo/evidence/paper-code-review-rerun-10.md` explicitly claims the runtime-checkable `Protocol` satisfies the typed boundary and that no `remove-ai-slops`/`programming` issue remains, but the direct adversarial pass above shows that claim is incomplete.

## userOutcomeReview

FAIL. Most session goals are supported, but the user-visible final outcome cannot be approved because the boundary still crashes for a non-protocol cache shape.

Supported checks:

- R10 direct calls are preserved inside the helper: `src/polysignal_lab/app/scheduler_reporting.py:297` calls `nautilus_cache.account()` and `:316` calls `nautilus_cache.positions()`.
- The exact previous `SimpleNamespace()` missing-method crash is fixed: fresh `tests/test_nautilus_reporting_cache_source.py` run passed `8` tests, and `SimpleNamespace()` returns `(1000.0, 1000.0, 0)`.
- G001 OrderBook safe slice is intact: active `src`/`tests` search has no `OrderBook.from_polymarket` or `from_polymarket(` references; parser behavior is in `src/polysignal_lab/data/orderbook_payload.py`; fresh orderbook/storage focused tests passed `35` tests.
- G002/G003 app-local audit retention is intact: `paper_trade_results` and `paper_wallet_snapshots` remain in `src/polysignal_lab/storage/sqlite_schema.py` with explicit app-local comments; `paper_orders`, `paper_fills`, and `paper_positions` active schema/domain definitions are absent.
- Protected refs are clean: fresh `git status --short -- refs @refs docs/nautilus_reference` and `git diff --name-only -- refs @refs docs/nautilus_reference` produced no output.
- No commit was made by this rerun; current HEAD is `3ef19dcf3ab39b0e1adf3951ed785145ac26f76d`.

Blocking check:

- Non-protocol cache boundary robustness is incomplete for non-callable protocol-shaped attributes.

## slopAndProgrammingPass

Direct `remove-ai-slops` pass: FAIL for overfit coverage. The new regression test covers only a cache with missing `account`/`positions` attributes. It does not cover malformed-but-attribute-present cache objects, so it gives false confidence for the stated non-protocol boundary.

Direct `programming` pass: FAIL for boundary typing. A runtime-checkable `Protocol` is not enough runtime parsing at this object boundary because it allows non-callable method attributes through to direct calls.

The code review report does include `remove-ai-slops` and `programming` sections, but that coverage is unsupported by the fresh adversarial evidence.

## checkedArtifactPaths

- `.omo/evidence/paper-goal-verification-rerun-10.md`
- `.omo/evidence/paper-code-review-rerun-10.md`
- `.omo/evidence/paper-qa-rerun-10.md`
- `.omo/evidence/paper-context-rerun-9.md`
- `.omo/evidence/paper-security-rerun-9.md`
- `.omo/evidence/paper-security-rerun-10.md`
- `.omo/ulw-loop/evidence/paper-r10-protocol-red.txt`
- `.omo/ulw-loop/evidence/paper-r10-protocol-green.txt`
- `.omo/ulw-loop/evidence/paper-r10-reporting-cache-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/storage/sqlite_schema.py`

## exactEvidenceGaps

- No passing artifact covers non-protocol cache objects with present but non-callable `account` or `positions` attributes.
- `.omo/evidence/paper-code-review-rerun-10.md` relies on `@runtime_checkable Protocol` as the boundary proof, but Python runtime protocols do not validate method callability/signatures.

## freshVerification

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_nautilus_reporting_cache_source.py
........                                                                 [100%]
```

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_orderbook_snapshot.py tests/test_storage_reporting_publish.py tests/test_storage_restore.py
...................................                                      [100%]
```

```text
git diff --check
<no output; exit 0>
```

## cleanupReceipt

No server, browser, tmux session, container, bound port, or long-running QA process was spawned.

<verdict>FAIL</verdict>
