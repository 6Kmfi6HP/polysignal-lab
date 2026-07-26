#!/usr/bin/env bash
# Run the native-migration quality gates and print the pass/fail table.
# Answers "is the migration complete for local/CI purposes?" — it does not
# cover live trading (out of scope until separately authorized).
#
# Gates: pytest (NAUTILUS_REQUIRED=1), pre-commit, polysignal-safety-scan,
# frontend lint/build/test, basedpyright vs .basedpyright/baseline.json.
#
# Not side-effect free: the frontend gate runs `npm run build`, which writes
# frontend/dist/ and regenerates frontend/src/routeTree.gen.ts. Check `git
# status` afterwards.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=".venv/bin/python"
[[ -x "$PY" ]] || PY="python3"
PRE_COMMIT=".venv/bin/pre-commit"
[[ -x "$PRE_COMMIT" ]] || PRE_COMMIT="pre-commit"

LOG_DIR="$(mktemp -d)"
trap 'rm -rf "$LOG_DIR"' EXIT

gates=()
failed=0

run_gate() {
  local name="$1"
  shift
  local log="$LOG_DIR/${name//[^A-Za-z0-9]/_}.log"
  printf '  %-12s running...' "$name"
  if "$@" >"$log" 2>&1; then
    printf '\r  %-12s PASS       \n' "$name"
    gates+=("PASS  $name")
  else
    printf '\r  %-12s FAIL       \n' "$name"
    gates+=("FAIL  $name")
    failed=1
    tail -15 "$log" | sed 's/^/      /'
  fi
}

echo "Native migration gates"
echo

run_gate "Tests" env NAUTILUS_REQUIRED=1 "$PY" -m pytest -q
run_gate "Pre-commit" "$PRE_COMMIT" run --all-files
run_gate "Safety" "$PY" scripts/safety_scan.py .
# Fails only on errors unbaselined in .basedpyright/baseline.json.
run_gate "Typecheck" "$PY" -m basedpyright
run_gate "Frontend" bash -c 'cd frontend && npm run lint && npm test && npm run build'
run_gate "Live default" "$PY" - <<'PY'
import sys

import yaml

from polysignal_lab.config import NautilusRuntimeConfig

fields = NautilusRuntimeConfig.model_fields
problems = []
if fields["execution_mode"].default != "sandbox":
    problems.append(f'execution_mode default is {fields["execution_mode"].default!r}, not "sandbox"')
if fields["allow_live_polymarket_execution"].default is not False:
    problems.append("allow_live_polymarket_execution does not default to False")

for path in ("config/signal_bot.yaml", "config/signal_bot.lab.yaml"):
    with open(path) as handle:
        mode = yaml.safe_load(handle)["runtime"]["nautilus"]["execution_mode"]
    if mode != "sandbox":
        problems.append(f"{path} sets execution_mode={mode!r}")

for problem in problems:
    print(problem, file=sys.stderr)
sys.exit(1 if problems else 0)
PY

echo
printf '%s\n' "${gates[@]}"
echo

if [[ "$failed" -eq 0 ]]; then
  echo "All gates pass: migration complete for local/CI purposes."
  echo "Live trading remains out of scope until separately authorized."
else
  echo "One or more gates failed — the migration is not complete." >&2
fi

exit "$failed"
