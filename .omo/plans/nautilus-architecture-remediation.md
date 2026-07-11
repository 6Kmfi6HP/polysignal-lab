# NautilusTrader Architecture Remediation Execution

Authoritative specification: `docs/superpowers/plans/2026-07-09-nautilus-architecture-remediation.md`.

Worktree: `/home/debian/polysignal-lab/.worktrees/nautilus-architecture-remediation`

## Constraints

- Execute and independently review one task per commit.
- Preserve every global constraint and exact acceptance command from the authoritative plan.
- Do not modify `@refs/` or `docs/nautilus_reference/`.
- Use focused TDD, the smallest correct diff, and real-surface QA for each task.
- Task 6 must pass its independent concurrency/lifecycle gate before Task 7 starts.

## TODOs

- [x] Task 1: Make Price-to-Beat CustomData replay deterministic (`f02a658`).
- [x] Task 2: Enforce absolute freshness for cross-market groups (`0291b2f`).
- [x] Task 3: Make MarketCatalog replacement atomic (`7b5429f`).
- [x] Task 4: Require one explicit shared decision policy (`0d10e4b`).
- [x] Task 5: Tighten runtime extension loading to one fixed shape (`fd67058`).
- [x] Task 6: Independently verify and, if needed, repair Actor-safe market discovery (`597bf2f`).
- [ ] Task 7: Eliminate the duplicate cross-market submission pipeline.
- [ ] Task 8: Remove verified dead runtime and legacy persistence code.
- [ ] Task 9: Consolidate optional Nautilus imports without breaking Python 3.11.
- [ ] Task 10: Remove high-value duplicate code without new frameworks.
- [ ] Task 11: Separate legacy snapshot adapters from PTB Alpha core.
- [ ] Task 12: Split VWAP trade history and state serialization from the core.
- [ ] Task 13: Clean current Ruff dead imports and local variables.

## Final Verification Wave

- [ ] Task 14: Run final architecture verification, real bridge/manual QA, global review/debugging gates, and refresh documentation.

## Acceptance

- Every task-specific command and observable in the authoritative plan passes or is recorded as a pre-existing/environment limitation.
- Each implementation DoneClaim is independently confirmed before its checkbox is marked complete.
- Final focused suite, full suite, static analysis, Python 3.12/Nautilus bridge check, review-work five-lane gate, and three-hypothesis runtime audit are recorded in `.omo/start-work/ledger.jsonl`.
- The worktree is clean, commits stay task-scoped, and protected reference directories are unchanged.
