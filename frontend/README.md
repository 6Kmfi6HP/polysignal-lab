# ![PolySignal Lab mark](public/images/polysignal-mark.svg) PolySignal Lab Dashboard

Read-only operations dashboard for PolySignal Lab signals, rejected signals,
paper-trading projections, leaderboard rows, strategy status, and system health.

## Origin

This frontend is adapted from
[satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin) under the MIT
license; see `LICENSE` in this directory. The upstream Clerk authentication and
demo CRUD pages were removed. The remaining app is a read-only SPA served by
nginx and backed by the existing PolySignal dashboard JSON API.

## Tech stack

- React 19 + TypeScript
- Vite
- TanStack Router
- TanStack Query
- Tailwind CSS + shadcn/ui primitives
- Vitest + Testing Library under jsdom

## Run locally

From the repository root:

```bash
cd frontend
npm ci
npm run dev
```

The Vite dev server proxies `/api/*` and `/health` to the compose
`dashboard-web` port (`http://localhost:8091` by default). Override with
`VITE_DASHBOARD_PROXY_TARGET` when pointing at a locally-run dashboard API.

## Verification

```bash
npm run lint
npm run build
npm test
```

## Container

The production image builds the SPA and serves `dist/` from nginx. nginx serves
the SPA shell and reverse-proxies `/api/*` plus `/health` to the compose
`dashboard-api` service.

## License

MIT. See `LICENSE`.
