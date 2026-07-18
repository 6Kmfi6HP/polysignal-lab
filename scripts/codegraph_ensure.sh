#!/usr/bin/env bash
# Ensure CodeGraph index is fresh when the live watcher is degraded or offline.
# Safe to run anytime; does not start a long-lived daemon (agents spawn MCP).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v codegraph >/dev/null 2>&1; then
  echo "codegraph CLI not on PATH; install from https://github.com/colbymchenry/codegraph" >&2
  exit 1
fi

if [[ ! -d .codegraph ]]; then
  echo "No .codegraph/ index — run: codegraph init" >&2
  exit 1
fi

force=0
quiet=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f) force=1 ;;
    --quiet|-q) quiet=1 ;;
    -h|--help)
      echo "Usage: $0 [--force] [--quiet]"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
  shift
done

needs_sync=0
needs_reindex=0
status_out="$(codegraph status 2>&1 || true)"

if [[ "$force" -eq 1 ]]; then
  needs_reindex=1
elif echo "$status_out" | grep -qiE 'never finished \(killed mid-index|index is truncated|references from an interrupted run|Index was built by an earlier version'; then
  needs_reindex=1
elif echo "$status_out" | grep -qiE 'Pending sync:|Pending Changes:|auto-sync is DISABLED|File watcher disabled|awaiting resolution|Run "codegraph sync"'; then
  needs_sync=1
elif echo "$status_out" | grep -qi 'Index is up to date'; then
  needs_sync=0
else
  # Ambiguous status — sync once to be safe.
  needs_sync=1
fi

if [[ "$needs_reindex" -eq 1 ]]; then
  if [[ "$quiet" -eq 0 ]]; then
    echo "Running codegraph index -f (truncated/outdated index)..."
  fi
  CODEGRAPH_NO_WATCHDOG=1 CODEGRAPH_NO_DAEMON=1 codegraph index -f
elif [[ "$needs_sync" -eq 1 ]]; then
  if [[ "$quiet" -eq 1 ]]; then
    codegraph sync --quiet
  else
    echo "Running codegraph sync..."
    codegraph sync
  fi
elif [[ "$quiet" -eq 0 ]]; then
  echo "CodeGraph index already up to date."
fi

if [[ "$quiet" -eq 0 ]]; then
  codegraph status
fi
