# Task 6 Report: Signals page

## Summary
- Replaced the Signals placeholder with Accepted/Rejected tabs.
- Accepted tab uses `useSignalsQuery()` and renders accepted signal rows by default.
- Rejected tab uses `useRejectedSignalsQuery()` and renders rejected signal rows after tab activation.
- Implemented loading, error, and empty states for both accepted and rejected datasets.
- Added jsdom/Testing Library coverage using `@testing-library/user-event`.

## TDD evidence
### RED
Command:

```bash
cd frontend && npm test -- src/features/signals/index.test.tsx
```

Observed before implementation:

```text
src/features/signals/index.test.tsx (5 tests | 5 failed)
Unable to find an element with the text: sig-accepted
Unable to find accessible element with the role "tab" and name "Rejected"
```

This failed for the expected reason: the placeholder page only rendered the Signals heading and had no accepted/rejected tabs or tables.

### GREEN
Command:

```bash
cd frontend && npm test -- src/features/signals/index.test.tsx
```

Observed after implementation:

```text
Test Files  1 passed (1)
Tests       5 passed (5)
```

## Additional verification
```bash
cd frontend && npm run lint
cd frontend && npm run build
```

Observed:
- `npm run lint` exited 0.
- `npm run build` exited 0; Vite built successfully.
- `git diff --check -- frontend/src/features/signals/index.tsx frontend/src/features/signals/index.test.tsx` produced no output.

## Review and self-review
- Code-reviewer pass reported no critical implementation issue and one important test-robustness concern: tab tests did not prove active/visible tab-panel behavior and loading assertion was unscoped.
- Addressed by asserting selected tab state, rejected content absence before click, accepted content absence after click, and scoping rejected content/loading assertions to the Rejected tabpanel.
- Self-review checked only Task 6 files and found no unrelated file changes before staging.

## Concerns
- None.
