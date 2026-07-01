# Task 4 Report: Sidebar navigation and route scaffolding

## Summary
- Replaced the template/demo sidebar data with the six PolySignal dashboard routes.
- Removed the old demo dashboard feature directory.
- Added six placeholder feature page modules with the downstream export names:
  - `OverviewPage`
  - `SignalsPage`
  - `PaperTradingPage`
  - `LeaderboardPage`
  - `StrategyStatusPage`
  - `SystemHealthPage`
- Pointed the authenticated index route at `OverviewPage`.
- Added authenticated route files for `/signals`, `/paper-trading`, `/leaderboard`, `/strategy-status`, and `/system-health`.
- Regenerated `frontend/src/routeTree.gen.ts` via `npm run build`.
- Migrated stale jsdom command palette tests from old demo navigation expectations to the new Task 4 sidebar routes.

## TDD Evidence

### RED
Command:

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Observed result before changing production sidebar data:

```text
FAIL  src/components/layout/data/sidebar-data.test.ts > sidebarData > lists Task 4 navigation routes in order
AssertionError: expected [ '/', undefined ] to deeply equal [ '/', '/signals', …(4) ]

Test Files  1 failed (1)
```

The failure matched the intended reason: the template sidebar did not expose the six Task 4 routes.

### GREEN after sidebar replacement
Command:

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Observed result:

```text
Test Files  1 passed (1)
Tests       1 passed (1)
```

### Regression follow-up for migrated jsdom tests
A full frontend test run after the route/sidebar migration exposed two stale Task 3 jsdom expectations in `src/context/search-provider.test.tsx` that still referenced the old demo navigation (`Dashboard`, `Errors Forbidden`, `/errors/forbidden`). These failures were caused by the Task 4 route/sidebar change, so the test was migrated to assert the new top-level routes.

Focused verification after migration:

```bash
cd frontend
npm test -- src/context/search-provider.test.tsx
```

Observed result from the focused run:

```text
1 test file passed, 8 tests passed
```

## Commands Run

```bash
# Worktree/isolation check
git rev-parse --git-dir
git rev-parse --git-common-dir
git branch --show-current
git rev-parse --show-superproject-working-tree
```

Result: work was already in the linked worktree `/home/gyue/polysignal-lab/.worktrees/dashboard-spa-refactor-2026-07-01` on branch `dashboard-spa-refactor-2026-07-01`.

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Result before implementation: failed as expected on the route-order assertion.

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Result after sidebar replacement: passed, 1 test file / 1 test.

```bash
rm -rf frontend/src/features/dashboard
```

Result: removed the old demo dashboard feature directory.

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Result after route/page scaffolding: passed, 1 test file / 1 test.

```bash
cd frontend
npm run build
```

Result: passed. `tsc -b` and `vite build` completed successfully; generated production chunks included the new route chunks for `signals`, `paper-trading`, `leaderboard`, `strategy-status`, and `system-health`.

```bash
cd frontend
npm test
```

Initial result: failed, 9 test files passed and 1 failed. The failed file was `src/context/search-provider.test.tsx`; failures were stale expectations for old demo navigation that no longer exists after Task 4.

```bash
cd frontend
npm test -- src/context/search-provider.test.tsx
```

Result after migrating stale expectations: passed, 1 test file / 8 tests.

```bash
cd frontend
npm test
```

Final result: passed, 10 test files / 69 tests.

## Verification Output

### Focused sidebar test

```text
Test Files  1 passed (1)
Tests       1 passed (1)
```

### Build

```text
> tsc -b && vite build
✓ 352 modules transformed.
✓ built in 841ms
```

Generated route tree evidence from `frontend/src/routeTree.gen.ts`:

```text
'/_authenticated/signals'
'/_authenticated/paper-trading'
'/_authenticated/leaderboard'
'/_authenticated/strategy-status'
'/_authenticated/system-health'
```

### Full frontend tests

```text
Test Files  10 passed (10)
Tests       69 passed (69)
```

## Files Changed

Modified:
- `frontend/src/components/layout/data/sidebar-data.ts`
- `frontend/src/context/search-provider.test.tsx`
- `frontend/src/routeTree.gen.ts`
- `frontend/src/routes/_authenticated/index.tsx`

Added:
- `frontend/src/components/layout/data/sidebar-data.test.ts`
- `frontend/src/features/overview/index.tsx`
- `frontend/src/features/signals/index.tsx`
- `frontend/src/features/paper-trading/index.tsx`
- `frontend/src/features/leaderboard/index.tsx`
- `frontend/src/features/strategy-status/index.tsx`
- `frontend/src/features/system-health/index.tsx`
- `frontend/src/routes/_authenticated/signals.tsx`
- `frontend/src/routes/_authenticated/paper-trading.tsx`
- `frontend/src/routes/_authenticated/leaderboard.tsx`
- `frontend/src/routes/_authenticated/strategy-status.tsx`
- `frontend/src/routes/_authenticated/system-health.tsx`

Deleted:
- `frontend/src/features/dashboard/index.tsx`
- `frontend/src/features/dashboard/components/analytics-chart.tsx`
- `frontend/src/features/dashboard/components/analytics.tsx`
- `frontend/src/features/dashboard/components/overview.tsx`
- `frontend/src/features/dashboard/components/recent-sales.tsx`

## Manual Browser QA

Skipped by instruction. The user forbids installing browsers on this device, and the task context explicitly says to skip the manual `npm run dev` browser navigation step here. Route scaffolding was verified with the focused sidebar test, `npm run build`, generated route tree inspection, and full jsdom/Vitest suite.

## Self-Review

- Sidebar route URLs are exactly `/`, `/signals`, `/paper-trading`, `/leaderboard`, `/strategy-status`, `/system-health` in order.
- Placeholder page modules export the names required by Tasks 5–10.
- Route file paths and `createFileRoute` IDs match the brief.
- The old demo dashboard feature was removed and no source imports `@/features/dashboard`.
- `frontend/src/routeTree.gen.ts` includes the five new authenticated child routes and `/` index route.
- No backend, Docker compose, CI, API client, progress ledger, or plan checklist files were modified.
