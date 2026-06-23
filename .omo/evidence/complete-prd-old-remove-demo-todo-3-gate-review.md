# Gate Review: complete-prd-old-remove-demo Todo 3

recommendation: REJECT

## originalIntent
Todo 3 was intended to replace product-owned demo fixtures with deterministic test-owned factories, migrate tests away from `polysignal_lab.app.demo_data` and `run_demo`, delete the demo runtime modules, remove the `polysignal-demo` script and Docker demo mode, and remove demo documentation claims without moving fake/demo code into product source.

## desiredOutcome
The user-visible outcome should be a codebase where the demo runtime surface is absent, tests depend only on `tests/` factories, packaging/Docker no longer expose a demo command, and docs no longer present demo/fake/offline workflows as delivered or current behavior.

## userOutcomeReview
The narrow executable acceptance command passes, focused tests pass twice, and `importlib.util.find_spec` cannot find `polysignal_lab.app.demo` or `polysignal_lab.app.demo_data`. However, the outcome is not fully satisfied from the user perspective because stale docs still describe demo/fake-data behavior, the plan still shows Todo 3 unchecked, and the new runtime-surface test is a deletion-only/tautological test that creates maintenance burden and false confidence rather than testing behavior.

## blockers
- Stale demo/fake-data documentation remains in `docs/IMPLEMENTATION_SUMMARY.md:21` and `docs/PRD_GAP_ANALYSIS.md:43`, `docs/PRD_GAP_ANALYSIS.md:75-83`, `docs/PRD_GAP_ANALYSIS.md:85-92`, `docs/PRD_GAP_ANALYSIS.md:105-107`, `docs/PRD_GAP_ANALYSIS.md:136-138`, `docs/PRD_GAP_ANALYSIS.md:144-145`, `docs/PRD_GAP_ANALYSIS.md:166-172`. This violates the Todo 3 requirement to remove demo docs claims, even though the narrower acceptance regex misses some of these strings.
- `tests/test_runtime_surface.py:6-7` is a deletion-only test that merely asserts the requested removal. Under the `remove-ai-slops` overfit/slop criteria, this is unresolved test slop and should be replaced by command/manual QA evidence or a broader runtime-surface contract test with real behavioral value.
- `.omo/plans/complete-prd-old-remove-demo.md` still has Todo 3 as `- [ ]`, while the evidence claims completion. That is a stale-state gap for start-work orchestration state.
- No separate code review report artifact with explicit programming + remove-ai-slops coverage was found in `.omo/evidence/`. The executor evidence includes a post-write scan, but the required independent code-review report coverage is absent.

## checkedArtifacts
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-3-complete-prd-old-remove-demo.txt`
- `.omo/evidence/task-5-complete-prd-old-remove-demo.txt`
- `tests/factories.py`
- `tests/conftest.py`
- `tests/test_orderbook_snapshot.py`
- `tests/test_paper_simulation.py`
- `tests/test_strategies.py`
- `tests/test_runtime_surface.py`
- `pyproject.toml`
- `docker-entrypoint.sh`
- `README.md`
- `docs/PRD_OLD_COMPLIANCE.md`
- `docs/TEST_RESULTS.md`
- `docs/IMPLEMENTATION_SUMMARY.md`
- `docs/PRD_GAP_ANALYSIS.md`
- `git status --short --untracked-files=all`

## directEvidence
- Deleted runtime files confirmed: `ls -la src/polysignal_lab/app/demo.py src/polysignal_lab/app/demo_data.py tests/test_demo_e2e.py` returned missing paths.
- Acceptance passed: `timeout 120 bash -lc 'test ! -e src/polysignal_lab/app/demo.py && test ! -e src/polysignal_lab/app/demo_data.py && ! rg "run_demo|demo_data|polysignal-demo|fake data|offline demo" src tests README.md docs pyproject.toml docker-entrypoint.sh'` exited 0.
- Focused tests passed twice: `timeout 120 .venv/bin/python -m pytest tests/test_orderbook_snapshot.py tests/test_paper_simulation.py -q` returned `11 passed` both runs.
- Runtime-surface test passed: `timeout 60 .venv/bin/python -m pytest tests/test_runtime_surface.py -q` returned `1 passed`.
- Import absence passed: `.venv/bin/python - <<'PY' ... find_spec(...) is None ... PY` printed both specs as `None`.
- CLI script absence confirmed in `pyproject.toml:26-28`, where only `polysignal-lab` and `polysignal-safety-scan` remain.
- Docker demo mode absence confirmed in `docker-entrypoint.sh:7-27`.
- Test-owned factories confirmed in `tests/factories.py`; `rg "sample_market|sample_book|sample_spot|fake|demo" src tests --glob '!**/__pycache__/**'` shows sample builders only in tests.
- Ignored stale bytecode remains under `src/polysignal_lab/app/__pycache__/demo*.pyc`; normal imports still resolve to `None`, but cleanup should remove caches during generated-history cleanup if final hygiene matters.

## exactEvidenceGaps
- The acceptance regex does not catch all stale docs claims, especially generic `demo` references and mixed-language fake-data claims.
- The plan checkbox was not updated, leaving orchestration state inconsistent with the done claim.
- The evidence file records bare `python` manual QA as unavailable, with only `.venv/bin/python` succeeding. This is acceptable for import absence but should be reflected accurately.
- The provided evidence does not include a standalone code-review report proving overfit/slop criteria coverage.
