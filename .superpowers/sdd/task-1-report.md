# Task 1 Report: Vendor and strip shadcn-admin template

## Summary

Vendored `satnaing/shadcn-admin` at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26` into `frontend/`, removed Clerk/auth and demo feature areas, switched the frontend to npm with `package-lock.json`, added template attribution to `frontend/README.md`, and kept the upstream MIT `LICENSE` in `frontend/`.

## Changes made

- Cloned upstream template into `frontend/`, checked out `e16c87f213a5ba5e45964e9b67c792105ec74d26`, and removed nested `.git` metadata.
- Removed the required Clerk/demo feature and route paths:
  - `src/features/auth/`, `src/features/chats/`, `src/features/tasks/`, `src/features/apps/`, `src/features/users/`, `src/features/settings/`
  - `src/routes/(auth)/`, `src/routes/clerk/`, `src/routes/_authenticated/{chats,tasks,apps,users,settings,help-center}/`
  - `src/assets/clerk-logo.tsx`, `src/assets/clerk-full-logo.tsx`
  - `pnpm-lock.yaml`
- Removed upstream `.env.example` because it contained only the stale Clerk publishable-key placeholder.
- Removed direct dependencies specified by the brief: `@clerk/react`, `@hookform/resolvers`, `input-otp`, `react-hook-form`, `zod`, and `@faker-js/faker`.
- Ran `npm install` to create and refresh `frontend/package-lock.json`.
- Regenerated the TanStack route tree through Vite (`npm exec vite -- build`) instead of hand-editing `src/routeTree.gen.ts`.
- Removed knip-reported unused files/dependencies outside retained shadcn UI primitives, including auth/sign-out leftovers and stale demo navigation references.
- Updated `frontend/README.md` with the required Origin section, npm run instructions, and removal of stale pnpm/Clerk/Auth visible claims.
- Added an env-gated Vitest/Playwright launch hook in `vite.config.ts` so `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser npm test` uses the existing system Chromium without installing browsers.

## Commands run and evidence

### RED / cleanup discovery

- `npm run knip` after initial deletion reported 32 unused files, 7 unused dependencies, 22 stale route imports in `src/routeTree.gen.ts`, and non-UI unused exports.
- Follow-up `npm run knip` after cleanup: pass, no findings.

### Route generation

- `npm exec vite -- build`: pass; regenerated `src/routeTree.gen.ts` via the TanStack Router Vite plugin and produced a Vite build.

### Package manager

- `npm install`: created `frontend/package-lock.json`.
- `npm install` after dependency cleanup: lockfile refreshed; removed now-unused packages.

### Verification

- `npm run knip`: pass, no findings.
- `npm run lint`: pass, `eslint .` completed with zero errors.
- `npm run build`: pass, `tsc -b && vite build` completed successfully.
- `npm run test:browser:install`: intentionally skipped because the user forbids browser installation.
- `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium-browser npm test`: blocked before test import/execution because the existing system Chromium is a snap wrapper that exits immediately:
  - `/usr/bin/chromium-browser: 12: xdg-settings: not found`
  - `snap-confine is packaged without necessary permissions and cannot continue`
  - `required permitted capability cap_dac_override not found`
- Also retried with `/snap/bin/chromium`; it failed with the same `snap-confine` capability error.
- Final retry added Playwright launch args `--no-sandbox` and `--disable-setuid-sandbox`; Chromium still exited with the same snap confinement error.

## Self-review

- Required deleted paths: checked with filesystem existence test; 17/17 required deleted paths are absent.
- Required files: `frontend/LICENSE`, `frontend/package.json`, `frontend/package-lock.json`, and `frontend/README.md` exist.
- Direct dependency cleanup: `frontend/package.json` no longer lists the brief's removed dependencies/devDependency.
- Dangling deleted imports/routes: grep found no source references to removed Clerk/auth/demo feature imports, deleted Clerk assets, or deleted route URLs under `frontend/src`.
- Stale Clerk env/config review: removed `frontend/.env.example`; remaining Clerk text is limited to README Origin attribution and upstream changelog history.
- Unused code/dependencies: `npm run knip` passes with no findings.
- Attribution: `frontend/README.md` includes the required `satnaing/shadcn-admin` Origin section with MIT license note, and the upstream `frontend/LICENSE` remains present.
- Package manager: no `pnpm-lock.yaml`; README run commands use npm.

## Concern

`npm test` could not be completed because the only allowed browser path available on this device (`/usr/bin/chromium-browser`, also `/snap/bin/chromium`) fails at launch due snap confinement/capability errors. Installing Playwright Chromium would likely resolve this, but browser installation is explicitly forbidden for this task, so the browser test step is recorded as blocked by usable-browser availability under that constraint.

## Task 1 fix: stale Clerk env placeholder

### Files changed

- Deleted `frontend/.env.example` because it contained only the stale `VITE_CLERK_PUBLISHABLE_KEY=` placeholder and no non-auth configuration.
- Appended this fix section to `.superpowers/sdd/task-1-report.md`.

### Verification

- `grep -R` equivalent via repository search over `frontend/` for `VITE_CLERK|CLERK_PUBLISHABLE|CLERK_SECRET|Clerk env|clerk env`: pass, no matches found.
- `cd frontend && npm run lint && npm run build`: pass; ESLint completed with zero reported errors, TypeScript build completed, and Vite production build completed successfully.
