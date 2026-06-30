# Dashboard SPA Refactor — Design

## Problem

The read-only operations dashboard (`src/polysignal_lab/dashboard/app.py`) renders its
home page as a ~300-line Python f-string that mixes inline CSS, manual HTML-table
string-concatenation, and business data formatting in a single function (`home()`).
There is no templating engine, no static asset pipeline, and no component structure.
This is functional but hard to maintain: every visual change requires editing a giant
string inside Python, and there is no way to add interactivity (auto-refresh, richer
navigation, charts) without making the string bigger.

The JSON API surface behind it (`/health`, `/api/overview`, `/api/signals`,
`/api/rejected-signals`, `/api/strategy-status`, `/api/paper-orders`, `/api/positions`,
`/api/trades`, `/api/leaderboard`) is already clean, well-tested, and read-only. It does
not need to change.

This document is a **research/design artifact only** — no implementation is in scope
for this round. It exists to define a concrete, low-risk target architecture for a
follow-up implementation plan.

## Goals

- Replace the hand-written HTML string with a properly structured, component-based
  frontend that is easy to extend and maintain.
- Keep the existing JSON API contract unchanged (zero risk to business logic).
- Match the project's existing deployment pattern: independent, single-purpose
  containers in `docker-compose.yml`, rather than bundling a Node build into the
  Python runtime image.
- Add auto-refresh and basic data visualization (charts) for the operator using the
  dashboard, since this is a live ops tool.
- Avoid building a frontend from scratch — adapt a maintained, MIT-licensed open-source
  starter template instead of hand-rolling layout/sidebar/theming primitives.

## Non-goals

- No authentication/authorization. The dashboard stays read-only and unauthenticated,
  exactly as today (`dashboard.read_only: true` in `config/signal_bot.yaml`).
- No changes to business logic, storage schema, or any `/api/*` response shape.
- No write endpoints of any kind (this is enforced today by
  `test_dashboard_rejects_write_methods` and stays enforced).

## Chosen template

[`satnaing/shadcn-admin`](https://github.com/satnaing/shadcn-admin) (MIT license,
actively maintained). Its stack lines up directly with the requirements gathered
during brainstorming:

| Requirement | Template already provides |
|---|---|
| React + TypeScript + Vite | Yes (React 19, Vite, TS) |
| Tailwind CSS | Yes (Tailwind v4 + shadcn/ui components) |
| Auto-refresh / data fetching with caching | TanStack Query (already a dependency) |
| Charts | Recharts (already a dependency) |
| Multi-page sidebar navigation | Built-in dashboard shell: sidebar, header,
  breadcrumbs, dark mode, command palette (Cmd+K), 404/500 error pages |

Parts of the template that will be **removed** during adaptation (not needed for this
project, and not carried into our codebase):

- Clerk-based sign-in/sign-up/forgot-password pages and auth guards (the dashboard has
  no login today and none is being added).
- Demo CRUD pages (Tasks, Apps, Users) and Settings sub-pages (account/appearance/
  notifications forms) — irrelevant to a read-only ops panel.
- Dependencies that become unused after the above removal (e.g. `@clerk/react`, and
  `react-hook-form` / `zod` / `input-otp` if no form ends up being needed,
  `@faker-js/faker` demo data generator).

The MIT license requires keeping the upstream copyright notice; the vendored
`frontend/` directory keeps the template's `LICENSE` file and the project README notes
the origin.

## Architecture

Three independently deployed containers (extends the existing two-container pattern in
`docker-compose.yml`, rather than collapsing frontend and backend into one image):

| Service | Build | Responsibility | Exposed port |
|---|---|---|---|
| `polysignal-lab` | existing Python `Dockerfile` | trading runtime — unchanged | none |
| `dashboard-api` | existing Python `Dockerfile`, `dashboard` command — unchanged | JSON-only: `/health`, `/api/*`. The `home()` HTML route is deleted. | container-internal only (or kept published for direct debugging) |
| `dashboard-web` | new `frontend/Dockerfile` (Node build stage → nginx runtime stage) | Serves the built SPA static assets; nginx reverse-proxies `/api/*` and `/health` to `dashboard-api` over the docker network | `8081:80` (replaces today's mapping to the FastAPI container) |

The browser only ever talks to `dashboard-web`'s single origin (no CORS to configure).
nginx forwards API calls to `dashboard-api` by Docker service name.

### Backend changes (`src/polysignal_lab/dashboard/app.py`)

- Delete the `home()` route and its inline HTML/CSS string.
- Keep every existing route and its handler logic byte-for-byte
  (`_health_payload`, `_calibration_from_reports`, `_bounded_limit`, the
  `/api/*` handlers). The numeric formatting helpers (`_fmt_money`, `_fmt_rate`,
  `_as_int`, `_as_float`) stay, since `_calibration_from_reports` still needs them;
  only the HTML-escaping helper (`_text`) becomes dead code and is removed.
- No change to `create_dashboard_app(store)`'s signature or to
  `run_dashboard_cli` in `src/polysignal_lab/app/main.py`.

### Frontend pages

The current single page's sections, plus two JSON endpoints that have no HTML
representation today, become six sidebar pages:

| Page | API source(s) | Replaces / adds | Chart |
|---|---|---|---|
| Overview | `/api/overview`, `/health` | Row-count cards + latest daily report summary (today's homepage top section) | none |
| Signals | `/api/signals`, `/api/rejected-signals` | Today's 5-row "recent signals" preview becomes a full paginated/filterable table, tabbed Accepted/Rejected | none |
| Paper Trading | `/api/paper-orders`, `/api/positions`, `/api/trades` | Today's 5-row "recent trades" preview becomes tabbed Orders/Positions/Trades tables | cumulative PnL line chart |
| Leaderboard | `/api/leaderboard` | Today's 5-row leaderboard preview becomes the full leaderboard + calibration breakdown | per-strategy PnL/win-rate bar chart |
| Strategy Status (new) | `/api/strategy-status` | Previously JSON-only, no UI at all | none |
| System Health (new) | `/health` | Previously just a static "Read-only" badge; now shows `components` and `recent_system_events` | none |

Each page uses a TanStack Query hook with `refetchInterval` (15s for signal/trade data,
30s for health) so the operator sees near-live data without manual reloads. Loading/
error/empty states use React Query's built-in `isPending`/`isError` rather than
hand-rolled state machines.

### Build & local dev

```
frontend/
  Dockerfile        # Node build stage -> nginx runtime stage
  nginx.conf        # static files + /api, /health reverse proxy to dashboard-api
  src/...           # adapted shadcn-admin source
  package.json
```

Local development runs `npm run dev` (Vite dev server) with Vite's `proxy` config
forwarding `/api` and `/health` to a locally running `dashboard-api`
(`uvicorn ... --port 8080`), matching today's quick local iteration loop without
requiring Docker.

### CI

A new, independent job is added to `.github/workflows/ci.yml` alongside the existing
`test` job (which is untouched):

```yaml
frontend:
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: frontend
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with: { node-version: '20' }
    - run: npm ci
    - run: npm run lint
    - run: npm run build
    - run: npm test
```

## Testing impact

- **Breaking change to `tests/test_dashboard.py`**: today's
  `test_dashboard_readonly_endpoints_return_stored_data` asserts HTML content
  (`signal["signal_id"] in html.text`, `"Paper rejects" in html.text`, etc.). After this
  refactor, `/` returns the static SPA shell — the data is fetched client-side by JS, not
  embedded server-side. Those specific assertions must be replaced with checks that `/`
  returns 200 with the SPA shell, and that unknown paths also fall back to the SPA shell.
  All `/api/*` JSON assertions are unaffected.
- **New frontend tests** use the template's existing Vitest + Playwright setup: each new
  page gets at least a render test, a "displays fetched data" test, and an empty/error
  state test.

## Rollout sequence (for the follow-up implementation plan)

1. Vendor `shadcn-admin` into `frontend/`; strip Clerk, demo pages, and unused deps; get
   the empty shell building and running with no real data wired in yet.
2. Wire Overview + Signals pages to the real API; validate end-to-end against a local
   `dashboard-api`.
3. Wire the remaining four pages (Paper Trading, Leaderboard, Strategy Status, System
   Health).
4. Remove `home()`'s HTML from the backend; update `tests/test_dashboard.py`.
5. Add the `dashboard-web` service + `frontend/nginx.conf` to `docker-compose.yml`; add
   the frontend CI job.
6. Local `docker compose up` smoke test across all three containers before cutover.

## Trade-offs and explicit decisions

- **More moving parts**: two containers become three, and there is a new nginx config
  to maintain. The trade is: the dashboard's UI code stops being a Python string and
  becomes a normal, testable frontend codebase.
- **New dependency surface**: a Node toolchain plus the template's dependencies (Radix
  UI primitives, the TanStack family, Recharts, Zustand). Unused pieces (Clerk, and
  `react-hook-form`/`zod`/`input-otp` if no form ends up being needed, the
  `@faker-js/faker` demo-data generator) are pruned during adaptation rather than kept
  "just in case."
- **MIT attribution**: the vendored `frontend/` keeps the upstream `LICENSE` file; the
  project README notes that the dashboard frontend is adapted from `shadcn-admin`.
- **Behavior change worth documenting**: today, `curl /` returns server-rendered data
  with no JS execution required. After this refactor, `curl /` returns only the SPA
  shell — real data requires hitting `/api/*` directly, which was already the
  machine-readable contract. This should be called out in any docs/scripts that assume
  `curl /` returns data.
