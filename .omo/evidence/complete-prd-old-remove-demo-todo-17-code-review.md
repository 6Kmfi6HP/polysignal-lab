# Todo 17 Self Review

## Mode surface
- PASS: `src/polysignal_lab/app/main.py` now exposes constrained CLI modes `scheduler`, `dashboard`, and bounded `smoke` through `--mode` and optional positional command.
- PASS: `--dashboard` remains only as a compatibility alias for dashboard.
- PASS: `docker-entrypoint.sh` supports only `scheduler`, `dashboard`, `test`, `shell`, and `smoke`; unknown modes fail usage.
- PASS: `docker run --rm polysignal-lab:prd-old demo` exits 1 with usage and no removed-mode execution.

## Docker test dependencies
- PASS: entrypoint `test` mode no longer performs `pip install`.
- PASS: Dockerfile installs `.[dev]` at build time and copies `pyproject.toml` plus `tests/` into runtime.
- PASS: `docker run --rm polysignal-lab:prd-old test` exits 0 with 119 passed.
- Risk: image build still resolves packages from the network. Runtime test execution is offline with packaged dependencies.

## Bounded smoke and once behavior
- PASS: `--once --real-readonly-smoke` runs a bounded local readiness hook, writes JSON evidence, and returns 0.
- PASS: smoke evidence records `network_calls=false`, `authenticated_endpoints=false`, and `trading_actions=false`.
- PASS: `--mode smoke` and entrypoint `smoke` map to the same bounded path.
- Residual for Todo 18: public market HTTP/WS checks are intentionally not implemented here; the evidence JSON records that live public checks remain.

## No real trading
- PASS: no changed runtime/packaging file contains private-key, authenticated client, order submit/create/cancel, or redeem symbols.
- PASS: bounded smoke builds configured strategies only and does not instantiate REST/WS clients, SQLite stores, or publisher calls.

## No removed aliases
- PASS: acceptance grep `! rg "demo|polysignal-demo" pyproject.toml docker-entrypoint.sh README.md docs src` passes.
- PASS: help output has no removed alias text.

## Slop / overfit risks
- PASS: tests exercise public CLI help, compatibility alias parsing, bounded smoke evidence, Docker build, Docker bad-mode, Docker smoke, and Docker test mode.
- PASS: touched Python files remain under 250 pure LOC: main.py 157, CLI test file 29.
- Minor risk: argparse help snapshot checks exact mode formatting; this is deliberate because stable explicit help is an acceptance requirement.

## Programming perspective
- PASS: CLI parsing uses a small typed boundary: `RuntimeMode` is a `StrEnum`, `CliOptions` is a frozen/slotted dataclass, and smoke evidence is a `TypedDict`.
- PASS: runtime dispatch uses an exhaustive `match` with `assert_never` for unreachable modes.
- PASS: the bounded smoke path is explicit about side effects and records `network_calls=false`, `authenticated_endpoints=false`, and `trading_actions=false`.
- PASS: Docker runtime test mode delegates to packaged pytest dependencies and does not run `pip install` in `docker-entrypoint.sh`.
- PASS: scoped safety grep over runtime/packaging files found no authenticated client, private-key, order submission, cancellation, redemption, or mnemonic symbols.
- PASS: touched Python files remain below the 250 pure LOC ceiling: `src/polysignal_lab/app/main.py` = 157 and `tests/test_cli_runtime_modes.py` = 29.
- Accepted inherited/project-convention risk: Docker build resolves dependencies at image build time, while Todo 17 only requires no ad hoc network install during Docker `test` runtime mode.

## Remove-ai-slops / overfit coverage
- PASS: tests assert public behavior rather than private implementation details: module help output, parsed dashboard alias, bounded smoke evidence, Docker bad-mode failure, Docker smoke, and Docker test mode.
- PASS: removal is not covered only by deletion checks. The suite also proves the supported replacement surfaces work: scheduler remains default, dashboard alias maps to dashboard, bounded smoke writes evidence, and Docker `test` runs packaged tests.
- PASS: no tautological test was added that only checks a hardcoded constant copied from implementation without exercising the public CLI or entrypoint surface.
- PASS: no implementation-mirroring parser, mode-normalizer, or wrapper abstraction was added just for tests; tests call `python -m polysignal_lab.app.main`, `parse_cli`, and the Docker entrypoint image surface.
- PASS: no unnecessary extraction, custom text parser, or broad compatibility alias was introduced. The only retained compatibility flag is existing `--dashboard`, scoped to dashboard and rejected when combined with command or `--mode`.
- PASS: no broad catch-all exception handling, sleeps, polling loops, process managers, network clients, or fake/demo fallback paths were added in Todo 17.
- PASS: the exact help-format assertion is intentional acceptance coverage for the public supported-mode list, not an overfit to an internal helper.

## Env secrecy
- PASS: no dotenv file was read.
- PASS: commands did not print or inspect credentials.
