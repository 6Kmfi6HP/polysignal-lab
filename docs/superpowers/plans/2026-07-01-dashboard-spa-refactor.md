# Dashboard SPA Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-written HTML string in the read-only dashboard with a maintainable React SPA (vendored from an open-source admin template), served from its own container that talks to the existing FastAPI JSON API.

**Architecture:** Three independently deployed containers: `polysignal-lab` (unchanged trading runtime), `dashboard-api` (existing FastAPI app, JSON-only — the hand-written `home()` HTML route is deleted), and a new `dashboard-web` (nginx serving a built React SPA, reverse-proxying `/api/*` and `/health` to `dashboard-api`). The SPA has 6 pages (Overview, Signals, Paper Trading, Leaderboard, Strategy Status, System Health) that poll the existing JSON endpoints via TanStack Query.

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui + TanStack Router + TanStack Query + Recharts, vendored from [`satnaing/shadcn-admin`](https://github.com/satnaing/shadcn-admin) (MIT license) pinned at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26`. Backend stays FastAPI/Python, unchanged except for deleting one route.

## Global Constraints

- The JSON shape and behavior of every existing `/api/*` endpoint and `/health` must not change.
- No authentication is added. The dashboard stays unauthenticated and read-only.
- No write (`POST`/`PUT`/`PATCH`/`DELETE`) endpoints are added anywhere; all existing write-rejection tests must keep passing.
- Frontend package manager is `npm` (the vendored template ships a pnpm lockfile; this plan replaces it with `package-lock.json` for consistency with the CI steps below).
- TanStack Query `refetchInterval` is `15_000` ms for signal/trade/order/position/leaderboard/strategy-status queries, `30_000` ms for the health query.
- Deployment is 3 containers in `docker-compose.yml`: `polysignal-lab` (unchanged), `dashboard-api` (FastAPI, container-internal only — no published port), `dashboard-web` (nginx, publishes `8081:80`, the only public entrypoint).
- The vendored `frontend/` directory keeps the upstream `LICENSE` file (MIT) and the project README must note the template origin.

## Note on task ordering

Task 11 (backend cleanup) touches only `src/polysignal_lab/dashboard/app.py` and `tests/test_dashboard.py`. It has no file overlap with any frontend task and can be done at any point in this sequence (including in parallel with Tasks 1–10) — it is placed after the frontend tasks here only because the design's rollout sequence listed it that way.

---

### Task 1: Vendor and strip the shadcn-admin template

**Files:**
- Create: `frontend/` (vendored from `satnaing/shadcn-admin` at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26`)
- Delete (within `frontend/`): `src/features/auth/`, `src/features/chats/`, `src/features/tasks/`, `src/features/apps/`, `src/features/users/`, `src/features/settings/`, `src/routes/(auth)/`, `src/routes/clerk/`, `src/routes/_authenticated/chats/`, `src/routes/_authenticated/tasks/`, `src/routes/_authenticated/apps/`, `src/routes/_authenticated/users/`, `src/routes/_authenticated/settings/`, `src/routes/_authenticated/help-center/`, `src/assets/clerk-logo.tsx`, `src/assets/clerk-full-logo.tsx`, `pnpm-lock.yaml`
- Modify: `frontend/package.json` (remove unused dependencies)
- Create: `frontend/package-lock.json` (via `npm install`)
- Modify: `frontend/README.md` (add template attribution)

**Interfaces:**
- Consumes: nothing (this is the first task; greenfield within the repo).
- Produces: a buildable `frontend/` Vite project with `npm run dev`, `npm run build`, `npm run lint`, `npm run test` all working, with Clerk and irrelevant demo pages removed. Later tasks add to this project.

- [x] **Step 1: Vendor the template at a pinned commit**

```bash
git clone https://github.com/satnaing/shadcn-admin.git frontend
cd frontend
git checkout e16c87f213a5ba5e45964e9b67c792105ec74d26
rm -rf .git
cd ..
```

- [x] **Step 2: Delete Clerk auth and irrelevant demo features**

```bash
cd frontend
rm -rf src/features/auth
rm -rf src/features/chats
rm -rf src/features/tasks
rm -rf src/features/apps
rm -rf src/features/users
rm -rf src/features/settings
rm -rf "src/routes/(auth)"
rm -rf src/routes/clerk
rm -rf src/routes/_authenticated/chats
rm -rf src/routes/_authenticated/tasks
rm -rf src/routes/_authenticated/apps
rm -rf src/routes/_authenticated/users
rm -rf src/routes/_authenticated/settings
rm -rf src/routes/_authenticated/help-center
rm -f src/assets/clerk-logo.tsx src/assets/clerk-full-logo.tsx
cd ..
```

- [x] **Step 3: Switch the package manager to npm and remove the pnpm lockfile**

```bash
rm frontend/pnpm-lock.yaml
```

- [x] **Step 4: Remove dependencies that are unused after the deletions above**

Open `frontend/package.json` and delete these lines from `"dependencies"`:

```json
    "@clerk/react": "^6.4.3",
    "@hookform/resolvers": "^5.2.2",
    "input-otp": "^1.4.2",
    "react-hook-form": "^7.72.1",
    "zod": "^4.3.6",
```

And this line from `"devDependencies"`:

```json
    "@faker-js/faker": "^10.4.0",
```

- [x] **Step 5: Install dependencies and generate the npm lockfile**

```bash
cd frontend
npm install
cd ..
```

Expected: `frontend/package-lock.json` is created. `npm install` completes with no error (some peer-dependency warnings about `react-day-picker`/`zod` version ranges from leftover transitive deps are expected and harmless at this point — they get cleaned up next).

- [x] **Step 6: Run the template's built-in unused-code detector and fix every finding**

```bash
cd frontend
npm run knip
```

This prints every file, export, and dependency that is no longer reachable after Step 2's deletions (this is exactly what `knip` is for — it ships as a devDependency and npm script in this template already). For each finding:
- **Unused file** (e.g. a leftover component only imported by something you deleted): delete it.
- **Unused dependency** (e.g. `react-day-picker`, `cmdk` if nothing imports it anymore): remove it from `package.json`.
- **Unused export**: leave it for now if it's part of a shadcn/ui primitive component (`src/components/ui/*`) — those are a component library, not all exports need to be consumed yet. Only delete unused exports in `src/features/`, `src/components/layout/`, `src/stores/`, `src/hooks/`, and `src/lib/`.

Re-run `npm run knip` after each round of fixes until it reports no findings outside of `src/components/ui/**` (knip is pre-configured in `vite.config.ts`'s test-coverage `exclude` list to skip that directory's pattern for coverage, but the `knip` script itself still scans it — unused shadcn/ui primitives are expected and fine to leave, since they are reusable building blocks for pages built in later tasks).

- [x] **Step 7: Run the full verification loop and fix any remaining TypeScript/lint errors**

```bash
cd frontend
npm run lint
npm run build
```

If either command reports an error referencing a deleted module (e.g. `Cannot find module '@/features/users'` in some file you haven't touched yet, such as `src/components/command-menu.tsx` or `src/components/layout/nav-user.tsx`), open that file and remove the dangling import and the JSX/code that used it. Repeat `npm run lint && npm run build` until both pass with zero errors. Do not run `npm run test` yet — `npm run test:browser:install` (Playwright's Chromium download) has not been run yet; that happens in Step 9.

- [x] **Step 8: Add template attribution to the frontend README**

Read `frontend/README.md` first, then add this section near the top (after the title, before "## Features" or equivalent):

```markdown
## Origin

This dashboard frontend is adapted from [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin)
(MIT license, see `LICENSE` in this directory). Authentication (Clerk) and the demo
CRUD pages (Tasks/Apps/Users/Settings/Chats) from the upstream template have been
removed; this project is a read-only operations dashboard with no user accounts.
```

- [x] **Step 9: Install the Playwright browser and run the existing template tests**

```bash
cd frontend
npm run test:browser:install
npm run test
```

Expected: all remaining tests (the ones belonging to components you didn't delete, e.g. `confirm-dialog.test.tsx`, `password-input.test.tsx`) pass. Delete any test file whose corresponding source file you deleted in Step 2/Step 6, if `npm run test` reports it as a missing-module failure.

Completion note: `npm run test:browser:install` was skipped because the user forbids installing browsers on this device. `npm test` was attempted with the existing system Chromium and blocked by snap Chromium confinement before test execution; browser-capable/manual verification remains deferred.

- [x] **Step 10: Commit**

```bash
git add frontend
git commit -m "feat(dashboard): vendor and strip shadcn-admin template into frontend/"
```

---

### Task 2: Frontend Docker image, nginx config, and local dev proxy

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Consumes: the buildable `frontend/` project from Task 1 (`npm run build` must produce `frontend/dist/`).
- Produces: `frontend/Dockerfile` (multi-stage Node build → nginx runtime) and `frontend/nginx.conf`, consumed by Task 12's `docker-compose.yml` change. The dev proxy in `vite.config.ts` is consumed by anyone running `npm run dev` locally in Tasks 5–10.

- [x] **Step 1: Add the dev-time API proxy to `vite.config.ts`**

Read `frontend/vite.config.ts` first (it should match the file fetched in Task 1, with `plugins`, `resolve`, and `test` keys in the `defineConfig({...})` call). Add a `server` key alongside them:

```ts
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
    },
  },
```

This forwards `/api/*` and `/health` requests made by `npm run dev` (default port 5173) to a `dashboard-api` running locally on port 8080 (started with `uvicorn` the same way `docker-entrypoint.sh dashboard` does), so local frontend development doesn't require Docker.

- [x] **Step 2: Write `frontend/nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://dashboard-api:8080/api/;
        proxy_set_header Host $host;
    }

    location /health {
        proxy_pass http://dashboard-api:8080/health;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

`dashboard-api` here is the Docker Compose service name added in Task 12; nginx resolves it via the compose network's built-in DNS.

Completion note: The plan's static `proxy_pass http://dashboard-api:8080/...` conflicted with Step 4's standalone `docker run` smoke because nginx resolves static upstreams at startup. User selected the lazy-DNS resolution: `frontend/nginx.conf` uses Docker DNS resolver `127.0.0.11` plus variable `proxy_pass` so standalone `/` smoke starts while `/api/*` and `/health` still proxy to `dashboard-api:8080` at request time in Compose.

- [x] **Step 3: Write `frontend/Dockerfile`**

```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [x] **Step 4: Build the image standalone and verify it serves the SPA shell**

```bash
docker build -t polysignal-dashboard-web ./frontend
docker run --rm -d --name dashboard-web-smoke -p 18081:80 polysignal-dashboard-web
sleep 2
curl -sf http://localhost:18081/ | grep -q '<div id="root">' && echo "SPA shell OK"
docker stop dashboard-web-smoke
```

Expected output: `SPA shell OK`. (The `/api` and `/health` proxy locations will fail at this point since no `dashboard-api` container/hostname exists yet outside the compose network — that's expected and gets verified in Task 14.)

- [x] **Step 5: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/vite.config.ts
git commit -m "feat(dashboard): add frontend Docker image, nginx reverse proxy, and dev API proxy"
```

---

### Task 3: Shared API client, types, and TanStack Query hooks

**Files:**
- Create: `frontend/src/lib/api/types.ts`
- Create: `frontend/src/lib/api/client.ts`
- Create: `frontend/src/lib/api/client.test.ts`
- Create: `frontend/src/lib/api/hooks.ts`
- Create: `frontend/src/test-utils/render-with-query-client.tsx`
- Create: `frontend/src/test-utils/fixtures.ts`

**Interfaces:**
- Consumes: the vendored project conventions from Task 1 (path alias `@` → `frontend/src`, TanStack Query already wired at the router root in `src/main.tsx`/`src/routes/__root.tsx` — no provider setup needed here for the app itself, only for tests).
- Produces (used by every page task, 5–10):
  - Types: `SignalCandidate`, `RejectedSignal`, `PaperOrder`, `PaperPosition`, `PaperTradeResult`, `DailyReport`, `CalibrationBucket`, `StrategyStatusRow`, `LeaderboardRow`, `OverviewResponse`, `LeaderboardResponse`, `HealthResponse`, `HealthComponent`.
  - Client functions: `getHealth`, `getOverview`, `getSignals(limit?)`, `getRejectedSignals(limit?)`, `getPaperOrders(status?, limit?)`, `getPositions(status?, limit?)`, `getTrades(limit?)`, `getLeaderboard(limit?)`, `getStrategyStatus(limit?)`, and the `ApiError` class.
  - Hooks: `useHealthQuery`, `useOverviewQuery`, `useSignalsQuery(limit?)`, `useRejectedSignalsQuery(limit?)`, `usePaperOrdersQuery(status?, limit?)`, `usePositionsQuery(status?, limit?)`, `useTradesQuery(limit?)`, `useLeaderboardQuery(limit?)`, `useStrategyStatusQuery(limit?)`.
  - Test helpers: `renderWithQueryClient(ui)`, and `make*` fixture factories.

- [x] **Step 1: Write the failing test for the API client**

Create `frontend/src/lib/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getOverview } from './client'

describe('getOverview', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the parsed JSON payload on success', async () => {
    const payload = {
      counts: { signals: 1 },
      latest_report: null,
      calibration_breakdown: {},
      strategy_status: [],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => payload,
      })
    )

    const result = await getOverview()

    expect(result).toEqual(payload)
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/overview'))
  })

  it('throws ApiError when the response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) })
    )

    await expect(getOverview()).rejects.toBeInstanceOf(ApiError)
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/lib/api/client.test.ts
```

Expected: FAIL with a module-resolution error — `./client` does not exist yet.

- [x] **Step 3: Write `frontend/src/lib/api/types.ts`**

```ts
export type Side = 'UP' | 'DOWN'
export type OrderStatus =
  | 'PENDING'
  | 'FILLED'
  | 'REJECTED'
  | 'RESTING'
  | 'CANCELLED'
  | 'PARTIAL'
export type PositionStatus = 'OPEN' | 'CLOSED'
export type TradeResultStatus = 'WIN' | 'LOSS' | 'VOID' | 'SPLIT' | 'UNKNOWN'
export type ExitMode =
  | 'RESOLUTION'
  | 'TAKE_PROFIT'
  | 'STOP_LOSS'
  | 'MAX_HOLD_TIME'
  | 'UNKNOWN'
export type CalibrationStatus = 'unknown' | 'insufficient_data' | 'calibrated'
export type StrategyStatus =
  | 'active'
  | 'disabled'
  | 'inactive'
  | 'unsupported_market'
  | 'missing_data'
  | 'uncalibrated'

export interface SignalCandidate {
  schema_version: number
  signal_id: string
  created_at: string
  strategy: string
  asset: string
  timeframe: string
  market_id: string
  market_slug: string
  condition_id: string
  token_id: string
  action: string
  side: Side
  confidence: number
  entry_reference_price: number
  max_entry_price: number
  seconds_to_close: number | null
  data_freshness_ms: number | null
  reason_codes: string[]
  metrics: Record<string, unknown>
  dedupe_key: string
  snapshot_id: string | null
  source_signal_ids: string[]
  order_intent: string | null
  expiry_seconds: number | null
  pair_id: string | null
  hedge_leg: boolean
}

export interface RejectedSignal {
  schema_version: number
  rejected_id: string
  candidate: SignalCandidate
  rejected_at: string
  gate_name: string
  reason_code: string
  details: Record<string, unknown>
}

export interface PaperOrder {
  schema_version: number
  paper_order_id: string
  signal_id: string
  created_at: string
  asset: string
  timeframe: string
  strategy: string
  market_id: string
  market_slug: string
  token_id: string
  side: Side
  order_type: string
  order_intent: string | null
  limit_price: number
  reference_price: number
  stake_usdc: number
  shares: number | null
  signal_confidence: number | null
  status: OrderStatus
  reject_reason: string | null
  metrics: Record<string, unknown>
}

export interface PaperPosition {
  schema_version: number
  paper_position_id: string
  signal_id: string
  paper_order_id: string
  paper_fill_id: string
  strategy: string
  asset: string
  timeframe: string
  market_id: string
  market_slug: string
  token_id: string
  side: Side
  entry_price: number
  shares: number
  stake_usdc: number
  signal_confidence: number | null
  opened_at: string
  status: PositionStatus
  closed_at: string | null
}

export interface PaperTradeResult {
  schema_version: number
  paper_trade_id: string
  signal_id: string
  paper_position_id: string
  strategy: string
  asset: string
  timeframe: string
  market_id: string
  market_slug: string
  side: Side
  entry_price: number
  shares: number
  stake_usdc: number
  exit_mode: ExitMode
  outcome_value: number
  settlement_value: number
  pnl_usdc: number
  roi: number
  result: TradeResultStatus
  opened_at: string
  closed_at: string
  details: Record<string, unknown>
}

export interface CalibrationBucket {
  strategy: string
  asset: string
  timeframe: string
  confidence_bucket: string
  sample_size: number
  wins: number
  losses: number
  calibration_status: CalibrationStatus
  [key: string]: unknown
}

export interface DailyReport {
  report_id: string
  report_date: string
  starting_equity: number
  ending_equity: number
  paper_pnl: number
  paper_roi: number
  total_signals: number
  paper_orders: number
  paper_fills: number
  rejected_paper_orders: number
  paper_rejects_by_reason: Record<string, number>
  average_execution_staleness_ms: number | null
  open_positions: number
  closed_positions: number
  win_count: number
  loss_count: number
  void_count: number
  win_rate: number
  total_pnl_usdc: number
  average_roi: number
  max_drawdown: number
  profit_factor: number | null
  strategy_breakdown: Record<string, unknown>
  calibration_breakdown: Record<string, CalibrationBucket>
  created_at: string
}

export interface StrategyStatusRow {
  strategy: string
  asset: string
  timeframe: string
  status: StrategyStatus
  reason: string | null
}

export interface LeaderboardRow {
  strategy: string
  closed_positions: number
  win_count: number
  loss_count: number
  void_count: number
  total_pnl_usdc: number
  average_roi: number
  win_rate: number
}

export interface OverviewResponse {
  counts: Record<string, number>
  latest_report: DailyReport | null
  calibration_breakdown: Record<string, CalibrationBucket>
  strategy_status: StrategyStatusRow[]
}

export interface LeaderboardResponse {
  leaderboard: LeaderboardRow[]
  calibration_breakdown: Record<string, CalibrationBucket>
}

export interface HealthComponent {
  name: string
  status: string
  last_success_at: string | null
  last_error_at: string | null
  last_error: string | null
  metrics: Record<string, unknown>
}

export interface HealthResponse {
  status: string
  generated_at: string | null
  components: HealthComponent[]
  counts: Record<string, number>
  recent_system_events: Record<string, unknown>[]
}
```

- [x] **Step 4: Write `frontend/src/lib/api/client.ts`**

```ts
import type {
  HealthResponse,
  LeaderboardResponse,
  OverviewResponse,
  PaperOrder,
  PaperPosition,
  PaperTradeResult,
  RejectedSignal,
  SignalCandidate,
  StrategyStatusRow,
} from './types'

const API_BASE = '/api'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined>
): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  const response = await fetch(url.toString())
  if (!response.ok) {
    throw new ApiError(response.status, `${path} failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function getHealth() {
  return request<HealthResponse>('/health')
}

export function getOverview() {
  return request<OverviewResponse>(`${API_BASE}/overview`)
}

export function getSignals(limit = 100) {
  return request<SignalCandidate[]>(`${API_BASE}/signals`, { limit })
}

export function getRejectedSignals(limit = 100) {
  return request<RejectedSignal[]>(`${API_BASE}/rejected-signals`, { limit })
}

export function getPaperOrders(status?: string, limit = 100) {
  return request<PaperOrder[]>(`${API_BASE}/paper-orders`, { status, limit })
}

export function getPositions(status?: string, limit = 100) {
  return request<PaperPosition[]>(`${API_BASE}/positions`, { status, limit })
}

export function getTrades(limit = 100) {
  return request<PaperTradeResult[]>(`${API_BASE}/trades`, { limit })
}

export function getLeaderboard(limit = 100) {
  return request<LeaderboardResponse>(`${API_BASE}/leaderboard`, { limit })
}

export function getStrategyStatus(limit = 100) {
  return request<StrategyStatusRow[]>(`${API_BASE}/strategy-status`, { limit })
}
```

- [x] **Step 5: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/lib/api/client.test.ts
```

Expected: PASS, 2 tests.

- [x] **Step 6: Write `frontend/src/lib/api/hooks.ts`**

```ts
import { useQuery } from '@tanstack/react-query'
import * as api from './client'

export const LIVE_REFRESH_MS = 15_000
export const HEALTH_REFRESH_MS = 30_000

export function useHealthQuery() {
  return useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
    refetchInterval: HEALTH_REFRESH_MS,
  })
}

export function useOverviewQuery() {
  return useQuery({
    queryKey: ['overview'],
    queryFn: api.getOverview,
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useSignalsQuery(limit = 100) {
  return useQuery({
    queryKey: ['signals', limit],
    queryFn: () => api.getSignals(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useRejectedSignalsQuery(limit = 100) {
  return useQuery({
    queryKey: ['rejected-signals', limit],
    queryFn: () => api.getRejectedSignals(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function usePaperOrdersQuery(status?: string, limit = 100) {
  return useQuery({
    queryKey: ['paper-orders', status, limit],
    queryFn: () => api.getPaperOrders(status, limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function usePositionsQuery(status?: string, limit = 100) {
  return useQuery({
    queryKey: ['positions', status, limit],
    queryFn: () => api.getPositions(status, limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useTradesQuery(limit = 100) {
  return useQuery({
    queryKey: ['trades', limit],
    queryFn: () => api.getTrades(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useLeaderboardQuery(limit = 100) {
  return useQuery({
    queryKey: ['leaderboard', limit],
    queryFn: () => api.getLeaderboard(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

export function useStrategyStatusQuery(limit = 100) {
  return useQuery({
    queryKey: ['strategy-status', limit],
    queryFn: () => api.getStrategyStatus(limit),
    refetchInterval: LIVE_REFRESH_MS,
  })
}
```

- [x] **Step 7: Write `frontend/src/test-utils/render-with-query-client.tsx`**

```tsx
import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from 'vitest-browser-react'

export function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
    },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
```

Completion note: User selected the non-browser Vitest resolution because browser installation is forbidden and existing snap Chromium cannot launch. The test helper uses Testing Library under jsdom instead of `vitest-browser-react`, preserving the same render-with-query-client interface while allowing `npm test` to pass without browser binaries.

- [x] **Step 8: Write `frontend/src/test-utils/fixtures.ts`**

```ts
import type {
  DailyReport,
  HealthResponse,
  LeaderboardResponse,
  OverviewResponse,
  PaperOrder,
  PaperPosition,
  PaperTradeResult,
  RejectedSignal,
  SignalCandidate,
  StrategyStatusRow,
} from '@/lib/api/types'

export function makeSignal(overrides: Partial<SignalCandidate> = {}): SignalCandidate {
  return {
    schema_version: 1,
    signal_id: 'sig-1',
    created_at: '2026-06-30T00:00:00+00:00',
    strategy: 'ptb_diff',
    asset: 'BTC',
    timeframe: '5m',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    condition_id: 'cond-1',
    token_id: 'token-up',
    action: 'BUY',
    side: 'UP',
    confidence: 0.7,
    entry_reference_price: 0.5,
    max_entry_price: 0.55,
    seconds_to_close: 120,
    data_freshness_ms: 50,
    reason_codes: [],
    metrics: {},
    dedupe_key: 'BTC:5m:mkt-1:UP:ptb_diff',
    snapshot_id: null,
    source_signal_ids: [],
    order_intent: null,
    expiry_seconds: null,
    pair_id: null,
    hedge_leg: false,
    ...overrides,
  }
}

export function makeRejectedSignal(
  overrides: Partial<RejectedSignal> = {}
): RejectedSignal {
  return {
    schema_version: 1,
    rejected_id: 'rej-1',
    candidate: makeSignal(),
    rejected_at: '2026-06-30T00:00:00+00:00',
    gate_name: 'freshness_gate',
    reason_code: 'STALE_SPOT_PRICE',
    details: {},
    ...overrides,
  }
}

export function makePaperOrder(overrides: Partial<PaperOrder> = {}): PaperOrder {
  return {
    schema_version: 1,
    paper_order_id: 'po-1',
    signal_id: 'sig-1',
    created_at: '2026-06-30T00:00:00+00:00',
    asset: 'BTC',
    timeframe: '5m',
    strategy: 'ptb_diff',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    token_id: 'token-up',
    side: 'UP',
    order_type: 'SIMULATED_MARKETABLE_LIMIT',
    order_intent: null,
    limit_price: 0.55,
    reference_price: 0.5,
    stake_usdc: 10,
    shares: 18,
    signal_confidence: 0.7,
    status: 'FILLED',
    reject_reason: null,
    metrics: {},
    ...overrides,
  }
}

export function makePaperPosition(
  overrides: Partial<PaperPosition> = {}
): PaperPosition {
  return {
    schema_version: 1,
    paper_position_id: 'pp-1',
    signal_id: 'sig-1',
    paper_order_id: 'po-1',
    paper_fill_id: 'pf-1',
    strategy: 'ptb_diff',
    asset: 'BTC',
    timeframe: '5m',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    token_id: 'token-up',
    side: 'UP',
    entry_price: 0.5,
    shares: 18,
    stake_usdc: 10,
    signal_confidence: 0.7,
    opened_at: '2026-06-30T00:00:00+00:00',
    status: 'OPEN',
    closed_at: null,
    ...overrides,
  }
}

export function makePaperTradeResult(
  overrides: Partial<PaperTradeResult> = {}
): PaperTradeResult {
  return {
    schema_version: 1,
    paper_trade_id: 'pt-1',
    signal_id: 'sig-1',
    paper_position_id: 'pp-1',
    strategy: 'ptb_diff',
    asset: 'BTC',
    timeframe: '5m',
    market_id: 'mkt-1',
    market_slug: 'btc-updown-5m',
    side: 'UP',
    entry_price: 0.5,
    shares: 18,
    stake_usdc: 10,
    exit_mode: 'RESOLUTION',
    outcome_value: 1,
    settlement_value: 1,
    pnl_usdc: 4,
    roi: 0.4,
    result: 'WIN',
    opened_at: '2026-06-30T00:00:00+00:00',
    closed_at: '2026-06-30T00:05:00+00:00',
    details: {},
    ...overrides,
  }
}

export function makeDailyReport(overrides: Partial<DailyReport> = {}): DailyReport {
  return {
    report_id: 'dr-1',
    report_date: '2026-06-30',
    starting_equity: 1000,
    ending_equity: 1004,
    paper_pnl: 4,
    paper_roi: 0.004,
    total_signals: 3,
    paper_orders: 3,
    paper_fills: 3,
    rejected_paper_orders: 0,
    paper_rejects_by_reason: {},
    average_execution_staleness_ms: 25,
    open_positions: 0,
    closed_positions: 1,
    win_count: 1,
    loss_count: 0,
    void_count: 0,
    win_rate: 1,
    total_pnl_usdc: 4,
    average_roi: 0.12,
    max_drawdown: 0,
    profit_factor: null,
    strategy_breakdown: {},
    calibration_breakdown: {},
    created_at: '2026-06-30T00:00:00+00:00',
    ...overrides,
  }
}

export function makeOverviewResponse(
  overrides: Partial<OverviewResponse> = {}
): OverviewResponse {
  return {
    counts: {
      signals: 3,
      rejected_signals: 1,
      paper_positions: 1,
      paper_trade_results: 1,
      daily_reports: 1,
    },
    latest_report: makeDailyReport(),
    calibration_breakdown: {},
    strategy_status: [],
    ...overrides,
  }
}

export function makeHealthResponse(
  overrides: Partial<HealthResponse> = {}
): HealthResponse {
  return {
    status: 'ok',
    generated_at: null,
    components: [],
    counts: {},
    recent_system_events: [],
    ...overrides,
  }
}

export function makeStrategyStatusRow(
  overrides: Partial<StrategyStatusRow> = {}
): StrategyStatusRow {
  return {
    strategy: 'ptb_diff',
    asset: 'ETH',
    timeframe: '5m',
    status: 'unsupported_market',
    reason: 'UNSUPPORTED_ASSET',
    ...overrides,
  }
}

export function makeLeaderboardResponse(
  overrides: Partial<LeaderboardResponse> = {}
): LeaderboardResponse {
  return {
    leaderboard: [
      {
        strategy: 'ptb_diff',
        closed_positions: 2,
        win_count: 1,
        loss_count: 1,
        void_count: 0,
        total_pnl_usdc: 4,
        average_roi: 0.12,
        win_rate: 0.5,
      },
    ],
    calibration_breakdown: {},
    ...overrides,
  }
}
```

- [x] **Step 9: Run the full frontend verification loop**

```bash
cd frontend
npm run lint
npm run build
npm test
```

Expected: all three pass.

- [x] **Step 10: Commit**

```bash
git add frontend/src/lib/api frontend/src/test-utils
git commit -m "feat(dashboard): add typed API client, TanStack Query hooks, and test fixtures"
```

---

### Task 4: Sidebar navigation and route scaffolding for the 6 pages

**Files:**
- Modify: `frontend/src/components/layout/data/sidebar-data.ts`
- Create: `frontend/src/components/layout/data/sidebar-data.test.ts`
- Delete: `frontend/src/features/dashboard/`
- Create: `frontend/src/features/overview/index.tsx` (placeholder; replaced in Task 5)
- Create: `frontend/src/features/signals/index.tsx` (placeholder; replaced in Task 6)
- Create: `frontend/src/features/paper-trading/index.tsx` (placeholder; replaced in Task 7)
- Create: `frontend/src/features/leaderboard/index.tsx` (placeholder; replaced in Task 8)
- Create: `frontend/src/features/strategy-status/index.tsx` (placeholder; replaced in Task 9)
- Create: `frontend/src/features/system-health/index.tsx` (placeholder; replaced in Task 10)
- Modify: `frontend/src/routes/_authenticated/index.tsx`
- Create: `frontend/src/routes/_authenticated/signals.tsx`
- Create: `frontend/src/routes/_authenticated/paper-trading.tsx`
- Create: `frontend/src/routes/_authenticated/leaderboard.tsx`
- Create: `frontend/src/routes/_authenticated/strategy-status.tsx`
- Create: `frontend/src/routes/_authenticated/system-health.tsx`

**Interfaces:**
- Consumes: nothing from Task 3 yet (pages are placeholders).
- Produces: exported components `OverviewPage`, `SignalsPage`, `PaperTradingPage`, `LeaderboardPage`, `StrategyStatusPage`, `SystemHealthPage` from their respective `@/features/<name>` modules — Tasks 5–10 replace each placeholder body in place, keeping the same export name and file path.

- [x] **Step 1: Write the failing test for the new sidebar structure**

Create `frontend/src/components/layout/data/sidebar-data.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { sidebarData } from './sidebar-data'

describe('sidebarData', () => {
  it('exposes exactly the six dashboard pages as top-level nav links', () => {
    const urls = sidebarData.navGroups.flatMap((group) =>
      group.items.filter((item) => 'url' in item && item.url).map((item) => item.url)
    )

    expect(urls).toEqual([
      '/',
      '/signals',
      '/paper-trading',
      '/leaderboard',
      '/strategy-status',
      '/system-health',
    ])
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Expected: FAIL — the assertion does not match the template's original demo nav items.

- [x] **Step 3: Replace `frontend/src/components/layout/data/sidebar-data.ts`**

```ts
import {
  Activity,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Radio,
  Trophy,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  user: {
    name: 'PolySignal Lab',
    email: 'read-only dashboard',
    avatar: '/avatars/shadcn.jpg',
  },
  teams: [
    {
      name: 'PolySignal Lab',
      logo: Gauge,
      plan: 'Read-only dashboard',
    },
  ],
  navGroups: [
    {
      title: 'Dashboard',
      items: [
        { title: 'Overview', url: '/', icon: LayoutDashboard },
        { title: 'Signals', url: '/signals', icon: Radio },
        { title: 'Paper Trading', url: '/paper-trading', icon: Activity },
        { title: 'Leaderboard', url: '/leaderboard', icon: Trophy },
        { title: 'Strategy Status', url: '/strategy-status', icon: ListChecks },
        { title: 'System Health', url: '/system-health', icon: Gauge },
      ],
    },
  ],
}
```

- [x] **Step 4: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/components/layout/data/sidebar-data.test.ts
```

Expected: PASS.

- [x] **Step 5: Delete the old demo dashboard feature**

```bash
rm -rf frontend/src/features/dashboard
```

- [x] **Step 6: Create the 6 placeholder feature pages**

Create `frontend/src/features/overview/index.tsx`:

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function OverviewPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>Overview</h1>
      </Main>
    </>
  )
}
```

Create `frontend/src/features/signals/index.tsx` (same pattern, `SignalsPage`, heading `Signals`):

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function SignalsPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>Signals</h1>
      </Main>
    </>
  )
}
```

Create `frontend/src/features/paper-trading/index.tsx` (`PaperTradingPage`, heading `Paper Trading`):

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function PaperTradingPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>Paper Trading</h1>
      </Main>
    </>
  )
}
```

Create `frontend/src/features/leaderboard/index.tsx` (`LeaderboardPage`, heading `Leaderboard`):

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function LeaderboardPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>Leaderboard</h1>
      </Main>
    </>
  )
}
```

Create `frontend/src/features/strategy-status/index.tsx` (`StrategyStatusPage`, heading `Strategy Status`):

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function StrategyStatusPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>Strategy Status</h1>
      </Main>
    </>
  )
}
```

Create `frontend/src/features/system-health/index.tsx` (`SystemHealthPage`, heading `System Health`):

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

export function SystemHealthPage() {
  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='text-2xl font-bold tracking-tight'>System Health</h1>
      </Main>
    </>
  )
}
```

- [x] **Step 7: Point the index route at `OverviewPage`**

Replace the contents of `frontend/src/routes/_authenticated/index.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { OverviewPage } from '@/features/overview'

export const Route = createFileRoute('/_authenticated/')({
  component: OverviewPage,
})
```

- [x] **Step 8: Create the 5 new route files**

Create `frontend/src/routes/_authenticated/signals.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { SignalsPage } from '@/features/signals'

export const Route = createFileRoute('/_authenticated/signals')({
  component: SignalsPage,
})
```

Create `frontend/src/routes/_authenticated/paper-trading.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { PaperTradingPage } from '@/features/paper-trading'

export const Route = createFileRoute('/_authenticated/paper-trading')({
  component: PaperTradingPage,
})
```

Create `frontend/src/routes/_authenticated/leaderboard.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { LeaderboardPage } from '@/features/leaderboard'

export const Route = createFileRoute('/_authenticated/leaderboard')({
  component: LeaderboardPage,
})
```

Create `frontend/src/routes/_authenticated/strategy-status.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { StrategyStatusPage } from '@/features/strategy-status'

export const Route = createFileRoute('/_authenticated/strategy-status')({
  component: StrategyStatusPage,
})
```

Create `frontend/src/routes/_authenticated/system-health.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { SystemHealthPage } from '@/features/system-health'

export const Route = createFileRoute('/_authenticated/system-health')({
  component: SystemHealthPage,
})
```

- [x] **Step 9: Regenerate the route tree and verify the build**

```bash
cd frontend
npm run build
```

Expected: PASS, and `src/routeTree.gen.ts` is regenerated to include the 5 new routes (the `tanstackRouter` Vite plugin does this automatically during `build`/`dev`). If the build reports an error in `src/components/command-menu.tsx` referencing the old `sidebarData` shape or deleted routes, open that file and follow the TypeScript error to fix the reference — the command palette is expected to read `sidebarData` generically and needs no route-specific changes beyond what Step 3 already provided.

- [x] **Step 10: Manually verify navigation**

```bash
npm run dev
```

Open the printed local URL, confirm the sidebar shows exactly: Overview, Signals, Paper Trading, Leaderboard, Strategy Status, System Health, and that clicking each one navigates to a page showing the matching heading. Stop the dev server (Ctrl-C).

Completion note: Manual browser navigation was skipped per user instruction prohibiting browser installation/testing on this device. Automated replacement evidence: focused sidebar test passed, `npm run build` regenerated the route tree with all five new routes, and the full jsdom frontend test suite passed.

- [x] **Step 11: Commit**

```bash
git add frontend/src
git commit -m "feat(dashboard): replace demo nav/pages with the 6 real dashboard routes"
```

---

### Task 5: Overview page

**Files:**
- Modify: `frontend/src/features/overview/index.tsx`
- Create: `frontend/src/features/overview/index.test.tsx`

**Interfaces:**
- Consumes: `useOverviewQuery`, `useHealthQuery` from Task 3; `makeOverviewResponse`, `makeHealthResponse` fixtures from Task 3; `renderWithQueryClient` from Task 3.
- Produces: the real `OverviewPage` (same export name/path as the Task 4 placeholder).

- [x] **Step 1: Write the failing test**

Create `frontend/src/features/overview/index.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { makeHealthResponse, makeOverviewResponse } from '@/test-utils/fixtures'
import { OverviewPage } from './index'

describe('OverviewPage', () => {
  it('renders row counts and the latest report once data loads', async () => {
    vi.spyOn(client, 'getOverview').mockResolvedValue(
      makeOverviewResponse({
        counts: { signals: 3, rejected_signals: 1 },
      })
    )
    vi.spyOn(client, 'getHealth').mockResolvedValue(
      makeHealthResponse({ status: 'ok' })
    )

    const { getByText } = await renderWithQueryClient(<OverviewPage />)

    await expect.element(getByText('3')).toBeInTheDocument()
    await expect.element(getByText('2026-06-30')).toBeInTheDocument()
    await expect.element(getByText('ok')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/features/overview/index.test.tsx
```

Expected: FAIL — the placeholder page only renders the heading "Overview", not row counts or report data.

- [x] **Step 3: Replace `frontend/src/features/overview/index.tsx`**

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealthQuery, useOverviewQuery } from '@/lib/api/hooks'

export function OverviewPage() {
  const overview = useOverviewQuery()
  const health = useHealthQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <div className='mb-4 flex items-center justify-between'>
          <h1 className='text-2xl font-bold tracking-tight'>Overview</h1>
          {health.data && (
            <Badge variant={health.data.status === 'ok' ? 'default' : 'destructive'}>
              {health.data.status}
            </Badge>
          )}
        </div>

        {overview.isPending && <Skeleton className='h-48 w-full' />}
        {overview.isError && (
          <p className='text-destructive'>
            Failed to load overview: {overview.error.message}
          </p>
        )}

        {overview.data && (
          <>
            <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-5'>
              {Object.entries(overview.data.counts).map(([table, count]) => (
                <Card key={table}>
                  <CardHeader className='pb-2'>
                    <CardDescription className='capitalize'>
                      {table.replace(/_/g, ' ')}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <CardTitle className='text-2xl'>{count}</CardTitle>
                  </CardContent>
                </Card>
              ))}
            </div>

            <Card className='mt-6'>
              <CardHeader>
                <CardTitle>Latest daily report</CardTitle>
              </CardHeader>
              <CardContent>
                {overview.data.latest_report ? (
                  <dl className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
                    <div>
                      <dt className='text-muted-foreground text-sm'>Report date</dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.report_date}
                      </dd>
                    </div>
                    <div>
                      <dt className='text-muted-foreground text-sm'>Total signals</dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.total_signals}
                      </dd>
                    </div>
                    <div>
                      <dt className='text-muted-foreground text-sm'>Closed positions</dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.closed_positions}
                      </dd>
                    </div>
                    <div>
                      <dt className='text-muted-foreground text-sm'>Paper PnL</dt>
                      <dd className='font-semibold'>
                        {overview.data.latest_report.total_pnl_usdc.toFixed(2)} USDC
                      </dd>
                    </div>
                  </dl>
                ) : (
                  <p className='text-muted-foreground'>
                    No daily report has been stored yet.
                  </p>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </Main>
    </>
  )
}
```

- [x] **Step 4: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/features/overview/index.test.tsx
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/overview
git commit -m "feat(dashboard): implement the Overview page"
```

---

### Task 6: Signals page

**Files:**
- Modify: `frontend/src/features/signals/index.tsx`
- Create: `frontend/src/features/signals/index.test.tsx`

**Interfaces:**
- Consumes: `useSignalsQuery`, `useRejectedSignalsQuery` from Task 3; `makeSignal`, `makeRejectedSignal` fixtures.
- Produces: the real `SignalsPage`.

- [x] **Step 1: Write the failing test**

Create `frontend/src/features/signals/index.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import { userEvent } from 'vitest/browser'
import * as client from '@/lib/api/client'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { makeRejectedSignal, makeSignal } from '@/test-utils/fixtures'
import { SignalsPage } from './index'

describe('SignalsPage', () => {
  it('shows accepted signals by default and rejected signals on the rejected tab', async () => {
    vi.spyOn(client, 'getSignals').mockResolvedValue([
      makeSignal({ signal_id: 'sig-accepted' }),
    ])
    vi.spyOn(client, 'getRejectedSignals').mockResolvedValue([
      makeRejectedSignal({ rejected_id: 'rej-1', reason_code: 'STALE_SPOT_PRICE' }),
    ])

    const { getByRole, getByText } = await renderWithQueryClient(<SignalsPage />)

    await expect.element(getByText('sig-accepted')).toBeInTheDocument()

    await userEvent.click(getByRole('tab', { name: 'Rejected' }))

    await expect.element(getByText('STALE_SPOT_PRICE')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/features/signals/index.test.tsx
```

Expected: FAIL — the placeholder page has no tabs or tables.

- [x] **Step 3: Replace `frontend/src/features/signals/index.tsx`**

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRejectedSignalsQuery, useSignalsQuery } from '@/lib/api/hooks'
import type { RejectedSignal, SignalCandidate } from '@/lib/api/types'

export function SignalsPage() {
  const signals = useSignalsQuery()
  const rejected = useRejectedSignalsQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Signals</h1>
        <Tabs defaultValue='accepted'>
          <TabsList>
            <TabsTrigger value='accepted'>Accepted</TabsTrigger>
            <TabsTrigger value='rejected'>Rejected</TabsTrigger>
          </TabsList>
          <TabsContent value='accepted'>
            {signals.isPending && <Skeleton className='h-64 w-full' />}
            {signals.isError && (
              <p className='text-destructive'>
                Failed to load signals: {signals.error.message}
              </p>
            )}
            {signals.data && <SignalsTable signals={signals.data} />}
          </TabsContent>
          <TabsContent value='rejected'>
            {rejected.isPending && <Skeleton className='h-64 w-full' />}
            {rejected.isError && (
              <p className='text-destructive'>
                Failed to load rejected signals: {rejected.error.message}
              </p>
            )}
            {rejected.data && <RejectedSignalsTable rejected={rejected.data} />}
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}

function SignalsTable({ signals }: { signals: SignalCandidate[] }) {
  if (signals.length === 0) {
    return <p className='text-muted-foreground'>No stored signals yet.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Signal</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Market</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Confidence</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {signals.map((signal) => (
          <TableRow key={signal.signal_id}>
            <TableCell className='font-mono text-xs'>{signal.signal_id}</TableCell>
            <TableCell>{signal.strategy}</TableCell>
            <TableCell>
              {signal.asset} {signal.timeframe}
            </TableCell>
            <TableCell>{signal.side}</TableCell>
            <TableCell>{(signal.confidence * 100).toFixed(1)}%</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function RejectedSignalsTable({ rejected }: { rejected: RejectedSignal[] }) {
  if (rejected.length === 0) {
    return <p className='text-muted-foreground'>No rejected signals yet.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Signal</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Gate</TableHead>
          <TableHead>Reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rejected.map((row) => (
          <TableRow key={row.rejected_id}>
            <TableCell className='font-mono text-xs'>
              {row.candidate.signal_id}
            </TableCell>
            <TableCell>{row.candidate.strategy}</TableCell>
            <TableCell>{row.gate_name}</TableCell>
            <TableCell>{row.reason_code}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

- [x] **Step 4: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/features/signals/index.test.tsx
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/signals
git commit -m "feat(dashboard): implement the Signals page"
```

---

### Task 7: Paper Trading page (with cumulative PnL chart)

**Files:**
- Modify: `frontend/src/features/paper-trading/index.tsx`
- Create: `frontend/src/features/paper-trading/index.test.tsx`

**Interfaces:**
- Consumes: `usePaperOrdersQuery`, `usePositionsQuery`, `useTradesQuery` from Task 3; `makePaperOrder`, `makePaperPosition`, `makePaperTradeResult` fixtures.
- Produces: the real `PaperTradingPage`.

- [x] **Step 1: Write the failing test**

Create `frontend/src/features/paper-trading/index.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import {
  makePaperOrder,
  makePaperPosition,
  makePaperTradeResult,
} from '@/test-utils/fixtures'
import { PaperTradingPage } from './index'

describe('PaperTradingPage', () => {
  it('renders the trades table with stored paper trades', async () => {
    vi.spyOn(client, 'getTrades').mockResolvedValue([
      makePaperTradeResult({ paper_trade_id: 'pt-1', pnl_usdc: 4 }),
    ])
    vi.spyOn(client, 'getPositions').mockResolvedValue([makePaperPosition()])
    vi.spyOn(client, 'getPaperOrders').mockResolvedValue([makePaperOrder()])

    const { getByText } = await renderWithQueryClient(<PaperTradingPage />)

    await expect.element(getByText('pt-1')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/features/paper-trading/index.test.tsx
```

Expected: FAIL — the placeholder page has no tabs or tables.

- [x] **Step 3: Replace `frontend/src/features/paper-trading/index.tsx`**

```tsx
import { useMemo } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  usePaperOrdersQuery,
  usePositionsQuery,
  useTradesQuery,
} from '@/lib/api/hooks'
import type { PaperOrder, PaperPosition, PaperTradeResult } from '@/lib/api/types'

export function PaperTradingPage() {
  const orders = usePaperOrdersQuery()
  const positions = usePositionsQuery()
  const trades = useTradesQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Paper Trading</h1>

        <Card className='mb-6'>
          <CardHeader>
            <CardTitle>Cumulative PnL</CardTitle>
          </CardHeader>
          <CardContent>
            {trades.isPending && <Skeleton className='h-64 w-full' />}
            {trades.data && <CumulativePnlChart trades={trades.data} />}
          </CardContent>
        </Card>

        <Tabs defaultValue='trades'>
          <TabsList>
            <TabsTrigger value='trades'>Trades</TabsTrigger>
            <TabsTrigger value='positions'>Positions</TabsTrigger>
            <TabsTrigger value='orders'>Orders</TabsTrigger>
          </TabsList>
          <TabsContent value='trades'>
            {trades.isError && (
              <p className='text-destructive'>
                Failed to load trades: {trades.error.message}
              </p>
            )}
            {trades.data && <TradesTable trades={trades.data} />}
          </TabsContent>
          <TabsContent value='positions'>
            {positions.isPending && <Skeleton className='h-64 w-full' />}
            {positions.isError && (
              <p className='text-destructive'>
                Failed to load positions: {positions.error.message}
              </p>
            )}
            {positions.data && <PositionsTable positions={positions.data} />}
          </TabsContent>
          <TabsContent value='orders'>
            {orders.isPending && <Skeleton className='h-64 w-full' />}
            {orders.isError && (
              <p className='text-destructive'>
                Failed to load orders: {orders.error.message}
              </p>
            )}
            {orders.data && <OrdersTable orders={orders.data} />}
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}

function CumulativePnlChart({ trades }: { trades: PaperTradeResult[] }) {
  const points = useMemo(() => {
    const sorted = [...trades].sort(
      (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
    )
    let cumulative = 0
    return sorted.map((trade) => {
      cumulative += trade.pnl_usdc
      return { closed_at: trade.closed_at, cumulative_pnl: cumulative }
    })
  }, [trades])

  if (points.length === 0) {
    return <p className='text-muted-foreground'>No closed paper trades yet.</p>
  }

  return (
    <ResponsiveContainer width='100%' height={240}>
      <LineChart data={points}>
        <CartesianGrid strokeDasharray='3 3' />
        <XAxis dataKey='closed_at' tick={false} />
        <YAxis />
        <Line type='monotone' dataKey='cumulative_pnl' stroke='currentColor' dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function TradesTable({ trades }: { trades: PaperTradeResult[] }) {
  if (trades.length === 0) {
    return <p className='text-muted-foreground'>No closed paper trades yet.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Trade</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Result</TableHead>
          <TableHead>PnL</TableHead>
          <TableHead>ROI</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.map((trade) => (
          <TableRow key={trade.paper_trade_id}>
            <TableCell className='font-mono text-xs'>{trade.paper_trade_id}</TableCell>
            <TableCell>{trade.strategy}</TableCell>
            <TableCell>{trade.result}</TableCell>
            <TableCell>{trade.pnl_usdc.toFixed(2)} USDC</TableCell>
            <TableCell>{(trade.roi * 100).toFixed(1)}%</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function PositionsTable({ positions }: { positions: PaperPosition[] }) {
  if (positions.length === 0) {
    return <p className='text-muted-foreground'>No stored positions yet.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Position</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Market</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Entry price</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((position) => (
          <TableRow key={position.paper_position_id}>
            <TableCell className='font-mono text-xs'>
              {position.paper_position_id}
            </TableCell>
            <TableCell>{position.strategy}</TableCell>
            <TableCell>
              {position.asset} {position.timeframe}
            </TableCell>
            <TableCell>{position.status}</TableCell>
            <TableCell>{position.entry_price.toFixed(3)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function OrdersTable({ orders }: { orders: PaperOrder[] }) {
  if (orders.length === 0) {
    return <p className='text-muted-foreground'>No stored orders yet.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Order</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Reject reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((order) => (
          <TableRow key={order.paper_order_id}>
            <TableCell className='font-mono text-xs'>{order.paper_order_id}</TableCell>
            <TableCell>{order.strategy}</TableCell>
            <TableCell>{order.status}</TableCell>
            <TableCell>{order.reject_reason ?? '-'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

- [x] **Step 4: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/features/paper-trading/index.test.tsx
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/paper-trading
git commit -m "feat(dashboard): implement the Paper Trading page with a cumulative PnL chart"
```

---

### Task 8: Leaderboard page (with PnL bar chart)

**Files:**
- Modify: `frontend/src/features/leaderboard/index.tsx`
- Create: `frontend/src/features/leaderboard/index.test.tsx`

**Interfaces:**
- Consumes: `useLeaderboardQuery` from Task 3; `makeLeaderboardResponse` fixture.
- Produces: the real `LeaderboardPage`.

- [x] **Step 1: Write the failing test**

Create `frontend/src/features/leaderboard/index.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { makeLeaderboardResponse } from '@/test-utils/fixtures'
import { LeaderboardPage } from './index'

describe('LeaderboardPage', () => {
  it('renders the leaderboard table with stored strategy rows', async () => {
    vi.spyOn(client, 'getLeaderboard').mockResolvedValue(
      makeLeaderboardResponse({
        leaderboard: [
          {
            strategy: 'late_consensus',
            closed_positions: 2,
            win_count: 1,
            loss_count: 0,
            void_count: 1,
            total_pnl_usdc: 4,
            average_roi: 0.12,
            win_rate: 0.5,
          },
        ],
      })
    )

    const { getByText } = await renderWithQueryClient(<LeaderboardPage />)

    await expect.element(getByText('late_consensus')).toBeInTheDocument()
    await expect.element(getByText('50.0%')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/features/leaderboard/index.test.tsx
```

Expected: FAIL — the placeholder page has no table.

- [x] **Step 3: Replace `frontend/src/features/leaderboard/index.tsx`**

```tsx
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLeaderboardQuery } from '@/lib/api/hooks'
import type { LeaderboardRow } from '@/lib/api/types'

export function LeaderboardPage() {
  const leaderboard = useLeaderboardQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Leaderboard</h1>

        {leaderboard.isPending && <Skeleton className='h-64 w-full' />}
        {leaderboard.isError && (
          <p className='text-destructive'>
            Failed to load leaderboard: {leaderboard.error.message}
          </p>
        )}

        {leaderboard.data && (
          <>
            <Card className='mb-6'>
              <CardHeader>
                <CardTitle>Total PnL by strategy</CardTitle>
              </CardHeader>
              <CardContent>
                <PnlByStrategyChart rows={leaderboard.data.leaderboard} />
              </CardContent>
            </Card>
            <LeaderboardTable rows={leaderboard.data.leaderboard} />
          </>
        )}
      </Main>
    </>
  )
}

function PnlByStrategyChart({ rows }: { rows: LeaderboardRow[] }) {
  if (rows.length === 0) {
    return <p className='text-muted-foreground'>No stored report rows yet.</p>
  }
  return (
    <ResponsiveContainer width='100%' height={240}>
      <BarChart data={rows}>
        <CartesianGrid strokeDasharray='3 3' />
        <XAxis dataKey='strategy' />
        <YAxis />
        <Bar dataKey='total_pnl_usdc' fill='currentColor' />
      </BarChart>
    </ResponsiveContainer>
  )
}

function LeaderboardTable({ rows }: { rows: LeaderboardRow[] }) {
  if (rows.length === 0) {
    return <p className='text-muted-foreground'>No stored report rows yet.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Strategy</TableHead>
          <TableHead>Closed</TableHead>
          <TableHead>Win rate</TableHead>
          <TableHead>Total PnL</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.strategy}>
            <TableCell className='font-mono text-xs'>{row.strategy}</TableCell>
            <TableCell>{row.closed_positions}</TableCell>
            <TableCell>{(row.win_rate * 100).toFixed(1)}%</TableCell>
            <TableCell>{row.total_pnl_usdc.toFixed(2)} USDC</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

- [x] **Step 4: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/features/leaderboard/index.test.tsx
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/leaderboard
git commit -m "feat(dashboard): implement the Leaderboard page with a PnL-by-strategy chart"
```

---

### Task 9: Strategy Status page

**Files:**
- Modify: `frontend/src/features/strategy-status/index.tsx`
- Create: `frontend/src/features/strategy-status/index.test.tsx`

**Interfaces:**
- Consumes: `useStrategyStatusQuery` from Task 3; `makeStrategyStatusRow` fixture.
- Produces: the real `StrategyStatusPage`.

- [x] **Step 1: Write the failing tests**

Create `frontend/src/features/strategy-status/index.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { makeStrategyStatusRow } from '@/test-utils/fixtures'
import { StrategyStatusPage } from './index'

describe('StrategyStatusPage', () => {
  it('renders one row per strategy/asset/timeframe combination', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockResolvedValue([
      makeStrategyStatusRow({ strategy: 'ptb_diff', asset: 'ETH', reason: 'UNSUPPORTED_ASSET' }),
    ])

    const { getByText } = await renderWithQueryClient(<StrategyStatusPage />)

    await expect.element(getByText('UNSUPPORTED_ASSET')).toBeInTheDocument()
  })

  it('shows an empty state when no rows are stored', async () => {
    vi.spyOn(client, 'getStrategyStatus').mockResolvedValue([])

    const { getByText } = await renderWithQueryClient(<StrategyStatusPage />)

    await expect
      .element(getByText('No strategy readiness rows recorded yet.'))
      .toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
cd frontend
npm test -- src/features/strategy-status/index.test.tsx
```

Expected: FAIL — the placeholder page has no table or empty state.

- [x] **Step 3: Replace `frontend/src/features/strategy-status/index.tsx`**

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useStrategyStatusQuery } from '@/lib/api/hooks'

export function StrategyStatusPage() {
  const status = useStrategyStatusQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>Strategy Status</h1>

        {status.isPending && <Skeleton className='h-64 w-full' />}
        {status.isError && (
          <p className='text-destructive'>
            Failed to load strategy status: {status.error.message}
          </p>
        )}
        {status.data && status.data.length === 0 && (
          <p className='text-muted-foreground'>No strategy readiness rows recorded yet.</p>
        )}
        {status.data && status.data.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Strategy</TableHead>
                <TableHead>Asset</TableHead>
                <TableHead>Timeframe</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Reason</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {status.data.map((row) => (
                <TableRow key={`${row.strategy}-${row.asset}-${row.timeframe}`}>
                  <TableCell>{row.strategy}</TableCell>
                  <TableCell>{row.asset}</TableCell>
                  <TableCell>{row.timeframe}</TableCell>
                  <TableCell>
                    <Badge variant={row.status === 'active' ? 'default' : 'secondary'}>
                      {row.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{row.reason ?? '-'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Main>
    </>
  )
}
```

- [x] **Step 4: Run the tests to verify they pass**

```bash
cd frontend
npm test -- src/features/strategy-status/index.test.tsx
```

Expected: PASS, 2 tests.

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/strategy-status
git commit -m "feat(dashboard): implement the Strategy Status page"
```

---

### Task 10: System Health page

**Files:**
- Modify: `frontend/src/features/system-health/index.tsx`
- Create: `frontend/src/features/system-health/index.test.tsx`

**Interfaces:**
- Consumes: `useHealthQuery` from Task 3; `makeHealthResponse` fixture.
- Produces: the real `SystemHealthPage`.

- [x] **Step 1: Write the failing test**

Create `frontend/src/features/system-health/index.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import * as client from '@/lib/api/client'
import { renderWithQueryClient } from '@/test-utils/render-with-query-client'
import { makeHealthResponse } from '@/test-utils/fixtures'
import { SystemHealthPage } from './index'

describe('SystemHealthPage', () => {
  it('renders component status badges from the health payload', async () => {
    vi.spyOn(client, 'getHealth').mockResolvedValue(
      makeHealthResponse({
        status: 'degraded',
        components: [
          {
            name: 'binance_ws',
            status: 'degraded',
            last_success_at: null,
            last_error_at: '2026-06-23T00:00:00+00:00',
            last_error: 'spot prices stale',
            metrics: { btc_spot_lag_ms: 61000 },
          },
        ],
      })
    )

    const { getByText } = await renderWithQueryClient(<SystemHealthPage />)

    await expect.element(getByText('binance_ws')).toBeInTheDocument()
    await expect.element(getByText('spot prices stale')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the test to verify it fails**

```bash
cd frontend
npm test -- src/features/system-health/index.test.tsx
```

Expected: FAIL — the placeholder page renders no health data.

- [x] **Step 3: Replace `frontend/src/features/system-health/index.tsx`**

```tsx
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealthQuery } from '@/lib/api/hooks'

export function SystemHealthPage() {
  const health = useHealthQuery()

  return (
    <>
      <Header>
        <div className='ml-auto flex items-center gap-2'>
          <Search />
          <ThemeSwitch />
        </div>
      </Header>
      <Main>
        <h1 className='mb-4 text-2xl font-bold tracking-tight'>System Health</h1>

        {health.isPending && <Skeleton className='h-64 w-full' />}
        {health.isError && (
          <p className='text-destructive'>Failed to load health: {health.error.message}</p>
        )}

        {health.data && (
          <>
            <div className='mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3'>
              {health.data.components.map((component) => (
                <Card key={component.name}>
                  <CardHeader className='flex items-center justify-between pb-2'>
                    <CardTitle className='text-sm font-medium'>
                      {component.name}
                    </CardTitle>
                    <Badge variant={component.status === 'ok' ? 'default' : 'destructive'}>
                      {component.status}
                    </Badge>
                  </CardHeader>
                  <CardContent className='text-muted-foreground text-sm'>
                    {component.last_error ?? 'No recent errors.'}
                  </CardContent>
                </Card>
              ))}
              {health.data.components.length === 0 && (
                <p className='text-muted-foreground'>
                  No component health rows recorded yet.
                </p>
              )}
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Recent system events</CardTitle>
              </CardHeader>
              <CardContent>
                {health.data.recent_system_events.length === 0 ? (
                  <p className='text-muted-foreground'>No system events recorded yet.</p>
                ) : (
                  <ul className='space-y-2'>
                    {health.data.recent_system_events.map((event, index) => (
                      <li key={index} className='font-mono text-xs'>
                        {JSON.stringify(event)}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </Main>
    </>
  )
}
```

- [x] **Step 4: Run the test to verify it passes**

```bash
cd frontend
npm test -- src/features/system-health/index.test.tsx
```

Expected: PASS.

- [x] **Step 5: Run the full frontend test suite, lint, and build**

```bash
cd frontend
npm run lint
npm run build
npm test
```

Expected: all pass. This is the last frontend-only task, so it's worth confirming the whole `frontend/` tree is clean before moving to backend/infra tasks.

- [x] **Step 6: Commit**

```bash
git add frontend/src/features/system-health
git commit -m "feat(dashboard): implement the System Health page"
```

---

### Task 11: Backend — remove the HTML route, update tests

**Files:**
- Modify: `src/polysignal_lab/dashboard/app.py`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: nothing from the frontend tasks (independent; can be done at any point — see "Note on task ordering" above).
- Produces: `create_dashboard_app(store)` with the same signature, same `/health` and `/api/*` routes, no `/` route.

- [x] **Step 1: Run the existing dashboard tests to see today's baseline**

```bash
pytest tests/test_dashboard.py -v
```

Expected: all tests currently pass (this confirms the starting point before the change).

- [x] **Step 2: Replace `src/polysignal_lab/dashboard/app.py`**

```python
from __future__ import annotations

from typing import TypeAlias

from fastapi import FastAPI

from polysignal_lab.storage.sqlite_store import SQLiteStore

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

CALIBRATION_MIN_SAMPLE_SIZE = 30


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def _fmt_money(value: JsonValue) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "0.00 USDC"
    return f"{amount:,.2f} USDC"


def _fmt_rate(value: JsonValue) -> str:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return "0.0%"
    return f"{rate * 100:.1f}%"


def _as_int(value: JsonValue) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: JsonValue) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _health_payload(store: SQLiteStore) -> dict[str, JsonValue]:
    counts = store.counts()
    recent_system_events = store.query_json(
        "system_events",
        where="ORDER BY created_at DESC, rowid DESC",
        limit=10,
    )
    snapshot = store.restore_latest_system_event("health_snapshot")
    if isinstance(snapshot, dict):
        return {
            "status": str(snapshot.get("status", "degraded")).lower(),
            "generated_at": snapshot.get("generated_at") or snapshot.get("created_at"),
            "components": snapshot.get("components", []),
            "counts": counts,
            "recent_system_events": recent_system_events,
        }
    return {
        "status": "ok",
        "generated_at": None,
        "components": [
            {
                "name": "sqlite_storage",
                "status": "ok",
                "last_success_at": None,
                "last_error_at": None,
                "last_error": None,
                "metrics": {"row_counts_available": True},
            }
        ],
        "counts": counts,
        "recent_system_events": recent_system_events,
    }


def _calibration_from_reports(reports: list[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    merged: dict[str, JsonValue] = {}
    average_weighted_sum: dict[str, dict[str, float]] = {}
    average_sample_size: dict[str, dict[str, int]] = {}
    count_keys = ("sample_size", "wins", "losses")
    for report in reports:
        rows = report.get("calibration_breakdown", {})
        if not isinstance(rows, dict):
            continue
        for bucket, raw_row in rows.items():
            if not isinstance(raw_row, dict):
                merged[bucket] = raw_row
                continue
            row = raw_row
            entry = merged.get(bucket)
            if not isinstance(entry, dict):
                entry = {
                    key: value
                    for key, value in row.items()
                    if key not in count_keys and not key.startswith("average_")
                }
                merged[bucket] = entry
            sample_size = _as_int(row.get("sample_size"))
            for key in count_keys:
                entry[key] = _as_int(entry.get(key)) + _as_int(row.get(key))
            for key, value in row.items():
                if key.startswith("average_"):
                    weighted_sum = average_weighted_sum.setdefault(bucket, {})
                    weighted_count = average_sample_size.setdefault(bucket, {})
                    weighted_sum[key] = weighted_sum.get(key, 0.0) + (
                        _as_float(value) * sample_size
                    )
                    weighted_count[key] = weighted_count.get(key, 0) + sample_size
    for bucket, entry in merged.items():
        if isinstance(entry, dict):
            sample_size = _as_int(entry.get("sample_size"))
            entry["calibration_status"] = (
                "calibrated"
                if sample_size >= CALIBRATION_MIN_SAMPLE_SIZE
                else "insufficient_data"
            )
            for key, weighted_sum in average_weighted_sum.get(bucket, {}).items():
                divisor = average_sample_size.get(bucket, {}).get(key, 0)
                entry[key] = weighted_sum / divisor if divisor else 0.0
    return merged


def create_dashboard_app(store: SQLiteStore) -> FastAPI:
    app = FastAPI(title="PolySignal Lab Dashboard", version="1.0.0")

    def strategy_status_rows(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "strategy_status",
            where="ORDER BY created_at ASC",
            limit=_bounded_limit(limit),
        )


    @app.get("/health", response_model=None)
    def health() -> dict[str, JsonValue]:
        return _health_payload(store)

    @app.get("/api/overview", response_model=None)
    def overview() -> dict[str, JsonValue]:
        counts = store.counts()
        latest_report = store.restore_daily_reports(limit=1)
        report = latest_report[0] if latest_report else None
        return {
            "counts": counts,
            "latest_report": report,
            "calibration_breakdown": (
                report.get("calibration_breakdown", {}) if report else {}
            ),
            "strategy_status": strategy_status_rows(),
        }

    @app.get("/api/signals", response_model=None)
    def signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "signals",
            where="ORDER BY created_at DESC",
            limit=_bounded_limit(limit),
        )

    @app.get("/api/rejected-signals", response_model=None)
    def rejected_signals(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json(
            "rejected_signals",
            where="ORDER BY rejected_at DESC",
            limit=_bounded_limit(limit),
        )

    @app.get("/api/strategy-status", response_model=None)
    def strategy_status(limit: int = 100) -> list[dict[str, JsonValue]]:
        return strategy_status_rows(limit)

    @app.get("/api/paper-orders", response_model=None)
    def paper_orders(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "paper_orders",
                where="WHERE status=? ORDER BY created_at DESC",
                params=(status.upper(),),
                limit=_bounded_limit(limit),
            )
        return store.query_json(
            "paper_orders",
            where="ORDER BY created_at DESC",
            limit=_bounded_limit(limit),
        )

    @app.get("/api/positions", response_model=None)
    def positions(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "paper_positions",
                where="WHERE status=? ORDER BY opened_at DESC",
                params=(status.upper(),),
                limit=_bounded_limit(limit),
            )
        return store.query_json(
            "paper_positions",
            where="ORDER BY opened_at DESC",
            limit=_bounded_limit(limit),
        )

    @app.get("/api/trades", response_model=None)
    def trades(limit: int = 100) -> list[dict[str, JsonValue]]:
        return store.query_json("paper_trade_results", limit=_bounded_limit(limit))

    @app.get("/api/leaderboard", response_model=None)
    def leaderboard(limit: int = 100) -> dict[str, JsonValue]:
        report_limit = _bounded_limit(limit)
        reports = store.restore_daily_reports(limit=report_limit)
        return {
            "leaderboard": store.restore_strategy_leaderboard(limit=report_limit),
            "calibration_breakdown": _calibration_from_reports(reports),
        }

    return app
```

This removes the `from html import escape` and `from fastapi.responses import HTMLResponse` imports (both only used by the deleted `home()` route and `_text` helper), the `_text` helper itself, and the entire `home()` route. Every other function and route is byte-for-byte unchanged from today.

- [x] **Step 3: Update `tests/test_dashboard.py` — `test_dashboard_readonly_endpoints_return_stored_data`**

In `tests/test_dashboard.py`, find this test and replace the `html = client.get("/")` line plus the HTML-content assertions at the end:

```python
    html = client.get("/")
```

becomes:

```python
    root = client.get("/")
```

and:

```python
    assert html.status_code == 200
    assert "<header" in html.text
    assert "<nav" in html.text
    assert "<main" in html.text
    assert "ptb_diff" in html.text
    assert signal["signal_id"] in html.text
    assert "Paper-only read model" in html.text
    assert "<form" not in html.text
    assert "<button" not in html.text
    assert "lorem" not in html.text.lower()
    assert "place order" not in html.text.lower()
    assert "create_" + "order" not in html.text
```

becomes:

```python
    assert root.status_code == 404
```

Also change the comment above it from `# Then: payloads contain the persisted rows and the HTML has no write controls.` to `# Then: payloads contain the persisted rows; the API no longer serves any HTML.`

- [x] **Step 4: Update `tests/test_dashboard.py` — `test_dashboard_rejects_write_methods`**

In the same file, find `test_dashboard_rejects_write_methods` and remove `"/"` from the `read_paths` tuple (it is no longer a registered route on this app, so it now 404s for every method instead of 405ing on writes):

```python
    read_paths = (
        "/",
        "/health",
```

becomes:

```python
    read_paths = (
        "/health",
```

- [x] **Step 5: Run the dashboard tests**

```bash
pytest tests/test_dashboard.py -v
```

Expected: all tests pass, including the two modified above.

- [x] **Step 6: Run the full test suite to check for regressions elsewhere**

```bash
pytest
```

Expected: PASS (no other test file references `create_dashboard_app`'s `/` route — confirm by searching first if this fails).

Completion note: Full pytest was run in the project venv during Task 11 and showed two Nautilus failures that were reproduced at the Task 11 base, outside this task's changed files. Task 11 focused dashboard and smoke tests passed; final acceptance still requires full pytest to be green after remediation.

- [x] **Step 7: Commit**

```bash
git add src/polysignal_lab/dashboard/app.py tests/test_dashboard.py
git commit -m "fix(dashboard): drop the hand-written HTML route, dashboard-api is JSON-only now"
```

---

### Task 12: Wire `dashboard-web` into `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `frontend/Dockerfile` from Task 2; the JSON-only `dashboard-api` behavior from Task 11.
- Produces: a `dashboard-web` compose service that other tooling (none yet) can depend on; this is the last piece needed before the Task 14 end-to-end smoke test.

- [ ] **Step 1: Replace the `dashboard` service in `docker-compose.yml`**

Read `docker-compose.yml` first to confirm the current `dashboard:` service block matches what's expected, then replace it (the `polysignal-lab:` service above it is untouched):

```yaml
  dashboard-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: polysignal-lab-dashboard-api
    restart: unless-stopped
    env_file:
      - .env
    environment:
      POLYSIGNAL_LAB__TELEGRAM__DRY_RUN: "true"
      POLYSIGNAL_LAB__DASHBOARD__HOST: "0.0.0.0"
      POLYSIGNAL_LAB__DASHBOARD__PORT: "8080"
    volumes:
      - ./data:/app/data:ro
      - ./logs:/app/logs:ro
      - ./state:/app/state:ro
      - ./config:/app/config:ro
    command: ["dashboard"]
    depends_on:
      polysignal-lab:
        condition: service_started
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s

  dashboard-web:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: polysignal-lab-dashboard-web
    restart: unless-stopped
    ports:
      - "0.0.0.0:8081:80"
    depends_on:
      dashboard-api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:80"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s
```

This renames the `dashboard` service to `dashboard-api` (matching its new JSON-only role), removes its `ports:` mapping (it's now internal-only, reached through `dashboard-web`'s nginx proxy), and adds the new `dashboard-web` service that owns the public `8081` port.

- [ ] **Step 2: Validate the compose file syntax**

```bash
docker compose config --quiet
```

Expected: no output, exit code 0 (this validates YAML structure and service references without starting anything).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(dashboard): split the dashboard compose service into dashboard-api and dashboard-web"
```

---

### Task 13: CI — add the frontend job

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `frontend/package.json` scripts (`lint`, `build`, `test`, `test:browser:install`) from Task 1.
- Produces: a `frontend` CI job, independent of and parallel to the existing `test` job.

- [ ] **Step 1: Add the `frontend` job to `.github/workflows/ci.yml`**

Read the file first to confirm the existing `test` job is still exactly as it was (it is not modified by this task), then add a new top-level job under `jobs:`:

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm ci
      - run: npm run test:browser:install
      - run: npm run lint
      - run: npm run build
      - run: npm test
```

`npm run test:browser:install` runs the template's pre-defined Playwright/Chromium install step (`playwright install chromium --with-deps`) — this is required because this template's `npm test` runs every test in a real headless Chromium instance via `vitest`'s browser mode, not jsdom.

- [ ] **Step 2: Verify the workflow YAML is well-formed**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add a frontend job for lint, build, and browser tests"
```

---

### Task 14: End-to-end smoke test across all three containers

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1–13.
- Produces: a verified, working three-container deployment.

- [ ] **Step 1: Build and start all three services**

```bash
docker compose build polysignal-lab dashboard-api dashboard-web
docker compose up -d polysignal-lab dashboard-api dashboard-web
```

- [ ] **Step 2: Wait for `dashboard-api` to report healthy**

```bash
timeout 60 bash -c 'until [ "$(docker inspect -f "{{.State.Health.Status}}" polysignal-lab-dashboard-api)" = "healthy" ]; do sleep 2; done'
echo "dashboard-api healthy"
```

Expected: `dashboard-api healthy` printed within 60 seconds.

- [ ] **Step 3: Curl the public entrypoint (`dashboard-web`) and verify the SPA shell, the API proxy, and the health proxy**

```bash
curl -sf http://localhost:8081/ | grep -q '<div id="root">' && echo "SPA shell OK"
curl -sf http://localhost:8081/api/overview | python3 -m json.tool | head -5
curl -sf http://localhost:8081/health | python3 -m json.tool | head -5
```

Expected: `SPA shell OK`, followed by valid JSON output (with `counts`, `latest_report`, etc. keys) for both `/api/overview` and `/health` — proving nginx is correctly proxying to `dashboard-api` over the compose network.

- [ ] **Step 4: Confirm `dashboard-api` itself is not publicly reachable on the host**

```bash
curl -sf http://localhost:8080/health 2>&1 | grep -qi "couldn't connect\|connection refused" && echo "dashboard-api correctly not published"
```

Expected: `dashboard-api correctly not published` (no port mapping was added for `dashboard-api` in Task 12, so port 8080 is not reachable from the host at all).

- [ ] **Step 5: Manual browser QA checklist**

Open `http://localhost:8081/` in a browser and confirm:
- The sidebar shows all 6 pages and each one loads without a console error.
- The Overview page shows row counts and (if any daily report rows exist in the mounted `./data` volume) the latest report summary.
- The Paper Trading and Leaderboard pages render their charts without errors (an empty chart with "No ... yet." text is expected if there's no data in the mounted volume).
- Data on at least one page changes within ~15–30 seconds without a manual page reload (confirms the `refetchInterval` polling is working).

- [ ] **Step 6: Tear down**

```bash
docker compose down
```

- [ ] **Step 7: Commit (if the manual QA step above led to any fixes)**

If Step 5 surfaced any bugs and you fixed them, commit those fixes individually with descriptive messages before considering this plan complete. If no fixes were needed, there is nothing to commit for this task.
