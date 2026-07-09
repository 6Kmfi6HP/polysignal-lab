# Paper QA Execution Review

Overall verdict: PASS with warnings.

QA surface: CLI behavioral regression from `/home/debian/polysignal-lab`.

Warnings:
- Worktree was already dirty before QA; I did not modify product files. This report and evidence directory are the only task-owned additions.
- NautilusTrader emitted two NumPy timedelta deprecation warnings in settlement/full pytest runs.
- `uv tool run pyscn analyze` without file args failed; rerun with `src tests --json` passed and produced a C grade, health 62/100.
- Existing unrelated server/browser-like processes were already present in the OS process table. Targeted Polysignal audit found only an existing codegraph MCP process for this repo, not a tmux/app/browser/server spawned by QA commands.

## manualQa.surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | cancelled-market dict-row settlement path | CLI pytest | `uv run pytest -p no:cacheprovider --no-header tests/test_scheduler_cancelled_markets.py::test_runtime_settles_cancelled_market_as_void_refund` | PASS, 1 passed | ART-1 |
| S2 | focused settlement suite | CLI pytest | `uv run pytest -p no:cacheprovider --no-header tests/test_scheduler_cancelled_markets.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py` | PASS, 10 passed, 2 warnings | ART-2 |
| S3 | broad regression | CLI pytest | `uv run pytest -p no:cacheprovider --no-header` | PASS, 651 passed, 2 warnings | ART-3 |
| S4 | syntax/import regression | CLI compileall | `PYTHONPYCACHEPREFIX=$(mktemp -d) uv run python -m compileall -q src tests` | PASS | ART-4 |
| S5 | whitespace regression | Git CLI | `git diff --check` | PASS | ART-5 |
| S6 | quality scan | CLI pyscn | `uv tool run pyscn analyze src tests --json` | PASS exit 0, grade C / health 62 | ART-6 |
| S7 | no refs mutation | Git CLI | `git status --short -- refs docs/nautilus_reference` | PASS, no output | ART-7 |
| S8 | no spawned tmux/server/browser process | OS process audit | `ps -eo pid,ppid,stat,comm,args | awk ...polysignal-lab...` | PASS with warning: only existing codegraph MCP process listed | ART-8 |

## manualQa.adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A1 | settlement row migration | void/cancelled outcome | Cancelled market settlement resolves as void refund through migrated path. | PASS | ART-1 |
| A2 | settlement suite | adjacent settlement regressions | Cancelled-market, settlement-resolution, and settlement unit surfaces remain green. | PASS | ART-2 |
| A3 | broad regression | hidden cross-module regression | Full test suite remains green after Nautilus alignment refactor. | PASS | ART-3 |
| A4 | environment hygiene | process spawn contamination | QA commands must not leave tmux/app/browser/server processes for Polysignal running. | PASS with warning | ART-8, ART-9 |
| A5 | protected reference tree | accidental refs/docs mutation | `refs` and `docs/nautilus_reference` remain unmodified. | PASS | ART-7 |
| A6 | quality gate drift | static quality regression | pyscn command completes and reports quality result for `src tests`. | PASS with warning grade C | ART-6, ART-10 |

## manualQa.artifactRefs

| id | kind | description | path |
|---|---|---|---|
| ART-1 | pytest transcript | Focused cancelled-market settlement test, 1 passed. | `.omo/evidence/paper-qa-execution-review/focused-cancelled-market.txt` |
| ART-2 | pytest transcript | Focused settlement suite, 10 passed with 2 Nautilus deprecation warnings. | `.omo/evidence/paper-qa-execution-review/focused-settlement-suite.txt` |
| ART-3 | pytest transcript | Full pytest suite, 651 passed with 2 Nautilus deprecation warnings. | `.omo/evidence/paper-qa-execution-review/full-pytest.txt` |
| ART-4 | compile transcript | `compileall` over `src tests`, exit 0. | `.omo/evidence/paper-qa-execution-review/compileall.txt` |
| ART-5 | git transcript | `git diff --check`, exit 0. | `.omo/evidence/paper-qa-execution-review/diff-check.txt` |
| ART-6 | pyscn transcript | Corrected pyscn scan over `src tests --json`, exit 0, health 62/C. | `.omo/evidence/paper-qa-execution-review/pyscn-src-tests.txt` |
| ART-7 | git transcript | `refs` and Nautilus reference docs status guard, no output. | `.omo/evidence/paper-qa-execution-review/refs-status.txt` |
| ART-8 | process transcript | Targeted Polysignal tmux/server/browser process audit. | `.omo/evidence/paper-qa-execution-review/process-audit-polysignal-targeted.txt` |
| ART-9 | process transcript | Broad before/after process audit showing pre-existing unrelated processes. | `.omo/evidence/paper-qa-execution-review/process-audit-before.txt`; `.omo/evidence/paper-qa-execution-review/process-audit-after.txt` |
| ART-10 | pyscn transcript | Failed discovery invocation showing `pyscn analyze` requires file args. | `.omo/evidence/paper-qa-execution-review/pyscn.txt` |
