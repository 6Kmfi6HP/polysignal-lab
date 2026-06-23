# Todo 17 Manual QA Notepad

## Happy QA - Docker Build
- Scenario: Docker image builds with runtime app, test deps, tests, and entrypoint.
- Invocation: `docker build -t polysignal-lab:prd-old .`
- Binary observable: exit 0; image exported and named `docker.io/library/polysignal-lab:prd-old`; final image sha `ae8e1b3a167291e4b14f352437686d785bf4840e82d8b0a3395063992e2d87e4`.
- Captured artifact path: `.omo/evidence/task-17-complete-prd-old-remove-demo.txt`

## Happy QA - Docker Test Mode
- Scenario: container test mode runs with packaged dependencies and no runtime install.
- Invocation: `docker run --rm polysignal-lab:prd-old test > /tmp/polysignal-docker-test.txt 2>&1`
- Binary observable: exit 0; `119 passed`; one `StarletteDeprecationWarning`.
- Captured artifact path: `/tmp/polysignal-docker-test.txt`

## Happy QA - Bounded Smoke
- Scenario: CLI smoke hook is bounded, local, read-only, and writes evidence.
- Invocation: `.venv/bin/python -m polysignal_lab.app.main --once --real-readonly-smoke --evidence /tmp/polysignal-smoke.json`
- Binary observable: exit 0; JSON evidence records `bounded=true`, `network_calls=false`, `authenticated_endpoints=false`, `trading_actions=false`, and `strategy_count=3`.
- Captured artifact path: `/tmp/polysignal-smoke.json`

## Failure QA - Docker Removed Mode
- Scenario: removed mode fails with usage and no execution.
- Invocation: `docker run --rm polysignal-lab:prd-old demo > /tmp/polysignal-docker-demo.txt 2>&1; rc=$?; test "$rc" -ne 0; ! rg "demo|polysignal-demo" /tmp/polysignal-docker-demo.txt`
- Binary observable: assertion harness exit 0; container command rc=1; output `Usage: /app/docker-entrypoint.sh {scheduler|dashboard|test|shell|smoke}`.
- Captured artifact path: `/tmp/polysignal-docker-demo.txt`

## Failure QA - Local Entrypoint Fallback
- Scenario: host fallback can exercise the same usage path if Docker is unavailable.
- Invocation: `APP_DIR=$PWD bash docker-entrypoint.sh demo > /tmp/polysignal-entrypoint-bad-mode.txt 2>&1; rc=$?; test "$rc" -ne 0; ! rg "demo|polysignal-demo" /tmp/polysignal-entrypoint-bad-mode.txt`
- Binary observable: assertion harness exit 0; script rc=1; output `Usage: docker-entrypoint.sh {scheduler|dashboard|test|shell|smoke}`.
- Captured artifact path: `/tmp/polysignal-entrypoint-bad-mode.txt`

## Acceptance QA
- Scenario: CLI help is stable and no removed surface remains in acceptance scope.
- Invocation: `.venv/bin/python -m polysignal_lab.app.main --help >/tmp/polysignal-help.txt`
- Binary observable: exit 0; help lists `--mode {scheduler,dashboard,smoke}`, `--once`, and `--real-readonly-smoke`; help has no removed alias text.
- Captured artifact path: `/tmp/polysignal-help.txt`
- Invocation: `! rg "demo|polysignal-demo" pyproject.toml docker-entrypoint.sh README.md docs src`
- Binary observable: exit 0 for negated grep; no matches.
- Captured artifact path: `.omo/evidence/task-17-complete-prd-old-remove-demo.txt`

## Cleanup QA
- Invocation: `docker ps --filter ancestor=polysignal-lab:prd-old --format '{{.ID}} {{.Status}} {{.Names}}'`
- Binary observable: exit 0 with no output.
- Captured artifact path: `.omo/evidence/task-17-complete-prd-old-remove-demo.txt`
