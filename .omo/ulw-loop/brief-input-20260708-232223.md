Continue unfinished Nautilus alignment refactor from session URLs:
- /tmp/ulw-cursor-75ed7e5d.md fetched from http://localhost:8082/api/v1/sessions/cursor:75ed7e5d-2fc1-4c44-a82c-2ccaa776d23d/md
- /tmp/ulw-omp-019f42fc.md fetched from http://localhost:8082/api/v1/sessions/omp:019f42fc-2a08-7000-9de6-3f3b86dc8562/md

Current durable state:
- Prior agents completed converter deletion, PaperOrder/PaperFill/PaperPosition/OrderStatus removal, SQLite paper order/fill/position table stripping, PaperTradeResult migration to dict rows, node_builder size-gate split, node test monkeypatch updates, R10 getattr collapse, and R3 paper_trade_results / paper_wallet_snapshots kept as app-local audit tables.
- The latest cursor session conclusion says the only explicit deferred item is independent OrderBook domain model removal/migration.
- User now says the first link's task is unfinished and asks to continue without stopping; therefore continue the remaining refactor instead of stopping at the deferred OrderBook item.

Constraints:
- Do not modify @refs.
- Do not commit unless explicitly required; prior session said do not commit.
- Consult docs/nautilus_reference/ for NautilusTrader work.
- Preserve dirty worktree changes; assume they are prior user/agent work.
- Use minimal diffs, tests first where behavior changes, and run focused plus broad verification.

Goal:
Complete the next remaining Nautilus alignment refactor slice: verify whether OrderBook domain model removal/migration is currently required and feasible from docs/architecture-nautilus-alignment.md and session checklist; if yes, migrate the smallest safe slice to Nautilus-native or row/dict boundary while preserving behavior. If architecture/doc evidence shows full removal is intentionally out of scope or unsafe, record blocker evidence and complete any smaller unblocked cleanup from the session checklist.

Expected criteria:
1. C1 Scope decision: docs/session/code search prove the exact remaining item(s), with evidence artifact .omo/ulw-loop/evidence/scope-decision.txt.
2. C2 Behavior pin + refactor: affected tests characterize current behavior before edits and pass after the smallest code change, artifact .omo/ulw-loop/evidence/orderbook-focused-pytest.txt.
3. C3 Real surface: run the matching CLI/test/API surface that exercises the migrated path (pytest or app endpoint depending on affected surface), artifact .omo/ulw-loop/evidence/orderbook-surface.txt.
4. C4 Regression: broad affected tests pass, artifact .omo/ulw-loop/evidence/orderbook-regression.txt.
