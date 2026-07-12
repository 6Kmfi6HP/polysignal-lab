# Generated History Deletion Manifest

## Approved Generated Paths For Later Deletion

The following paths are approved generated history/runtime outputs. A later cleanup task may delete them if present, after confirming no scoped evidence file is being removed:

- `logs/`
- `state/`
- `data/paper_trades.sqlite`
- `data/polysignal_lab.sqlite3`
- `scan_results.json`
- `refined_results.json`

Equivalent generated outputs that are also safe to remove when created by local runs:

- `data/*.sqlite`
- `data/*.sqlite3`
- `.pytest_cache/`
- `.ruff_cache/`
- `.mypy_cache/`
- `.coverage`
- `htmlcov/`
- `__pycache__/`
- `*.pyc`

Deletion rule: delete generated history only. Do not delete source, docs, tests, configuration, plans, evidence, or credential files.

## Paths Never To Touch

These paths are never approved for read, delete, copy, evidence capture, or credential discovery in this work plan:

- `.env`
- `.env.*`
- `*.pem`
- `*.key`
- Any file or variable containing wallet secrets, mnemonics, API secrets, Telegram bot tokens, Telegram channel identifiers, Polymarket authenticated credentials, Binance API keys, or authenticated trading credentials.

These project paths are source/control/evidence surfaces and are not generated history deletion targets:

- `src/`
- `tests/`
- `docs/`
- `config/`
- `.omo/plans/`
- `.omo/evidence/`
- `.git/`
- `.gitignore`
- `README.md`
- `pyproject.toml`
- `uv.lock`
- `Dockerfile`
- `docker-compose.yml`

## Operator Checklist For Later Cleanup

1. Run `git status --short` before deletion and preserve unrelated user/agent changes.
2. Confirm the target is listed under "Approved Generated Paths For Later Deletion".
3. Confirm the target is not listed under "Paths Never To Touch".
4. Remove only generated history/runtime outputs.
5. Re-run acceptance checks, including `test -e .env || true` without reading `.env`.
