# Todo 17 Gate Review

recommendation: APPROVE
verdict: CONFIRM
date: 2026-06-22
latestReview: 2026-06-22T07:46:05Z evidence-only re-gate after code-review artifact repair

## originalIntent

Todo 17 in `.omo/plans/complete-prd-old-remove-demo.md:235` asks to update CLI, Docker, packaging, and runtime modes. The plan requires supported modes to remain limited to scheduler, dashboard, test, shell, and a bounded smoke command; remove demo from CLI/Docker/docs; avoid demo aliases; ensure Docker test mode does not perform ad hoc runtime dependency installs when dependencies are already packaged or document/build accordingly.

## desiredOutcome

The user should be able to run CLI help without seeing a removed demo surface, grep the runtime/package/docs/source acceptance scope with no `demo` or `polysignal-demo` matches, build the Docker image, see `docker run ... demo` fail with usage instead of executing removed behavior, and run Docker test mode using build-packaged dependencies.

## userOutcomeReview

The shipped runtime behavior matches the requested user-visible outcome: CLI help lists only `scheduler`, `dashboard`, and `smoke`; Docker exposes `scheduler`, `dashboard`, `test`, `shell`, and `smoke`; Docker bad mode `demo` exits nonzero with usage; Docker test mode passes without runtime `pip install`; and the acceptance grep returns no matches.

Evidence-only re-gate result: the repaired code-review artifact now satisfies the prior evidence blocker. `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:34` through `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:41` explicitly covers the programming perspective, including typed CLI boundary, exhaustive runtime dispatch, bounded smoke side effects, Docker runtime dependency behavior, scoped safety grep, and LOC ceiling. `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:43` through `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:50` explicitly covers remove-ai-slops/overfit criteria, including public-behavior tests, deletion-only-test avoidance, tautological-test avoidance, implementation-mirroring-test avoidance, no needless parser/normalizer/wrapper abstraction, no broad compatibility alias, and no fake/demo fallback path.

## blockers

None for the current evidence-only re-gate.

Prior blocker resolved: the previous gate rejected because `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md` lacked explicit remove-ai-slops/programming coverage. The repaired artifact now covers that gap at `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:34` through `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:50`.

## directSlopAndProgrammingPass

Direct pass result: no unresolved implementation slop found in the inspected diff.

- `src/polysignal_lab/app/main.py:24` through `src/polysignal_lab/app/main.py:30` uses a typed runtime enum and mode values; no demo alias.
- `src/polysignal_lab/app/main.py:96` through `src/polysignal_lab/app/main.py:121` parses CLI options through a typed dataclass and rejects incompatible dashboard/smoke options.
- `src/polysignal_lab/app/main.py:137` through `src/polysignal_lab/app/main.py:160` implements bounded smoke as local evidence generation with `network_calls=false`, `authenticated_endpoints=false`, and `trading_actions=false`.
- `src/polysignal_lab/app/main.py:168` through `src/polysignal_lab/app/main.py:182` uses exhaustive `match` plus `assert_never`.
- `tests/test_cli_runtime_modes.py:11` through `tests/test_cli_runtime_modes.py:52` covers observable CLI help, dashboard compatibility, and bounded smoke evidence. I did not find excessive, tautological, deletion-only, or implementation-mirroring tests.
- Pure LOC check: `src/polysignal_lab/app/main.py` = 157; `tests/test_cli_runtime_modes.py` = 29. Both are below the 250 pure LOC ceiling.

## checkedArtifactPaths

- `.omo/plans/complete-prd-old-remove-demo.md`
- `src/polysignal_lab/app/main.py`
- `tests/test_cli_runtime_modes.py`
- `docker-entrypoint.sh`
- `Dockerfile`
- `pyproject.toml`
- `README.md`
- `docs/`
- `.omo/evidence/task-17-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md`
- `.omo/evidence/todo-17-manual-qa-notepad.md`
- `/tmp/polysignal-help-gate.txt`
- `/tmp/polysignal-docker-demo-gate.txt`
- `/tmp/polysignal-docker-test-gate.txt`
- `/tmp/polysignal-docker-smoke-gate.txt`

## commandsRun

Evidence-only re-gate commands:

- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/remove-ai-slops/SKILL.md` and `sed -n '261,620p' .../remove-ai-slops/SKILL.md`: exit 0; required skill loaded.
- `sed -n '1,280p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/SKILL.md`: exit 0; required skill loaded.
- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/references/python/README.md`: exit 0; Python programming reference loaded.
- `sed -n '1,520p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/references/code-smells.md`: exit 0 across two reads; code-smell reference loaded.
- `git status --short -- .omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md .omo/evidence/task-17-complete-prd-old-remove-demo.txt .omo/start-work/ledger.jsonl .omo/evidence/complete-prd-old-remove-demo-todo-17-gate-review.md src/polysignal_lab/app/main.py tests/test_cli_runtime_modes.py docker-entrypoint.sh Dockerfile pyproject.toml README.md docs`: exit 0; confirms shared dirty worktree, with evidence files present and product files still dirty from the existing Todo 17 work.
- `sed -n '1,320p' .omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md`: exit 0; repaired artifact now contains explicit programming and remove-ai-slops sections.
- `sed -n '1,260p' .omo/evidence/task-17-complete-prd-old-remove-demo.txt`: exit 0; task evidence records evidence-only repair and no product files edited during repair.
- `tail -n 20 .omo/start-work/ledger.jsonl`: exit 0; ledger records the first evidence-only rejection and artifact repair.
- `if rg "demo|polysignal-demo" pyproject.toml docker-entrypoint.sh README.md docs src; then exit 1; else exit 0; fi`: exit 0; no removed-mode text in acceptance scope.
- `.venv/bin/python -m pytest tests/test_cli_runtime_modes.py -q`: exit 0; `3 passed`.
- `if rg -n "pip install|pytest pytest-asyncio" docker-entrypoint.sh; then exit 1; else exit 0; fi`: exit 0; no runtime install in Docker entrypoint.
- `.venv/bin/python -m polysignal_lab.app.main --help >/tmp/polysignal-help-regate.txt`: exit 0; help still lists only `scheduler`, `dashboard`, and `smoke` for the Python CLI.
- `if rg -n "SecureClient|AsyncSecureClient|ClobClient\\(|create_order|post_order|submit_order|cancel_order|cancel_all|redeem_positions|private_key|mnemonic|api_secret|secret_key|order_args" src/polysignal_lab/app/main.py docker-entrypoint.sh Dockerfile pyproject.toml; then exit 1; else exit 0; fi`: exit 0; no forbidden runtime/package symbols.
- `docker ps --filter ancestor=polysignal-lab:prd-old --format '{{.ID}} {{.Status}} {{.Names}}'`: exit 0 with no output; no long-lived containers from this image.

Prior gate commands:

- `rg --files -g 'AGENTS.md' -g '!**/.env*'`: exit 1 after printing repo path; no repo-scoped `AGENTS.md` found.
- `for f in /AGENTS.md /home/AGENTS.md /home/gyue/AGENTS.md /home/gyue/polysignal-lab/AGENTS.md; do ...; done`: exit 0 with no output; no parent-scope `AGENTS.md` found.
- `sed -n '1,240p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/remove-ai-slops/SKILL.md`: exit 0; required skill loaded.
- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/SKILL.md`: exit 0; required skill loaded.
- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/references/python/README.md`: exit 0; Python programming reference loaded.
- `sed -n '1,620p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/references/code-smells.md`: exit 0 across two reads; code-smell reference loaded.
- `git status --short`: exit 0; worktree is heavily dirty with many unrelated changes and untracked files.
- `git diff -- src/polysignal_lab/app/main.py tests/test_cli_runtime_modes.py docker-entrypoint.sh Dockerfile pyproject.toml README.md docs .omo/evidence/task-17-complete-prd-old-remove-demo.txt .omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md .omo/evidence/todo-17-manual-qa-notepad.md`: exit 0; tracked diff showed runtime CLI and entrypoint changes.
- `.venv/bin/python -m polysignal_lab.app.main --help >/tmp/polysignal-help-gate.txt`: exit 0; help file written.
- `if rg "demo|polysignal-demo" pyproject.toml docker-entrypoint.sh README.md docs src; then exit 1; else exit 0; fi`: exit 0; no matches.
- `.venv/bin/python -m pytest tests/test_cli_runtime_modes.py -q`: exit 0; `3 passed`.
- `docker --version`: exit 0; Docker version `29.0.2`, build `8108357`.
- `rg -n "pip install|pytest pytest-asyncio" docker-entrypoint.sh`: exit 1; no runtime install command in entrypoint.
- `if rg -n "SecureClient|AsyncSecureClient|ClobClient\\(|create_order|post_order|submit_order|cancel_order|cancel_all|redeem_positions|private_key|mnemonic|api_secret|secret_key|order_args" src/polysignal_lab/app/main.py docker-entrypoint.sh Dockerfile pyproject.toml; then exit 1; else exit 0; fi`: exit 0; no forbidden runtime/package symbols.
- `.venv/bin/python -m pytest -q`: exit 0; `119 passed`, one StarletteDeprecationWarning.
- `docker build -t polysignal-lab:prd-old .`: exit 0; image `sha256:ae8e1b3a167291e4b14f352437686d785bf4840e82d8b0a3395063992e2d87e4`.
- `docker run --rm polysignal-lab:prd-old demo >/tmp/polysignal-docker-demo-gate.txt 2>&1 ...`: assertion harness exit 0; container rc `1`; output `Usage: /app/docker-entrypoint.sh {scheduler|dashboard|test|shell|smoke}`; no removed mode text.
- `docker run --rm polysignal-lab:prd-old test >/tmp/polysignal-docker-test-gate.txt 2>&1 ...`: exit 0; `119 passed`, one StarletteDeprecationWarning.
- `docker run --rm polysignal-lab:prd-old smoke --evidence /tmp/container-smoke-gate.json >/tmp/polysignal-docker-smoke-gate.txt 2>&1 ...`: exit 0; output included bounded smoke start and success messages.
- `docker ps --filter ancestor=polysignal-lab:prd-old --format '{{.ID}} {{.Status}} {{.Names}}'`: exit 0 with no output; no long-lived containers left behind.
- `for f in src/polysignal_lab/app/main.py tests/test_cli_runtime_modes.py; do ... awk ...; done`: exit 0; pure LOC `157` and `29`.

## findings

- No current blockers.
- Resolved prior blocker: `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:34` through `.omo/evidence/complete-prd-old-remove-demo-todo-17-code-review.md:50` now explicitly covers the programming and remove-ai-slops/overfit review criteria.

## residualRisks

- Docker build uses network during image build; Docker runtime `test` mode does not perform ad hoc installs.
- `README.md:31` through `README.md:36` documents `python -m pip install -e '.[dev]'`, while the programming skill prefers `uv`. This is pre-existing/project-convention adjacent documentation, not a Todo 17 behavior blocker.
- Smoke is intentionally bounded/local for Todo 17; plan line `.omo/plans/complete-prd-old-remove-demo.md:248` leaves public live market smoke for Todo 18.
- Worktree remains shared and heavily dirty; this review did not revert or normalize unrelated changes.
- No `.env` file was read.
