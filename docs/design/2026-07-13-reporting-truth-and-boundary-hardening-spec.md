# Reporting Truth and Runtime Boundary Hardening

## Problem Statement

PolySignal has completed the Nautilus runtime cutover tracked by GitHub Issue #1: Nautilus owns live execution, Cache, Portfolio, positions, and market-data runtime truth. The remaining issues are outside that cutover. They concern how PolySignal turns runtime events into reports, dashboard state, Telegram output, smoke validation, and compatibility surfaces.

Today, the reporting path can treat best-effort telemetry as complete historical truth, expose append-only lifecycle events as current dashboard state, publish externally before durable local state exists, and retain daily reports that become stale after late settlement. The dashboard can report `ok` when only SQLite is reachable, and reporting uses an inconsistent sandbox-currency fallback. Dashboard, Telegram, readonly smoke, and alpha compatibility code also retain duplicated parsing or projection logic that can drift over time.

The result is a lab system that may place and observe native Nautilus activity correctly while showing incomplete, stale, duplicated, or misleading reporting data. The project needs one simple, durable reporting read-model boundary without reintroducing a second execution engine or duplicating Nautilus runtime ownership.

## Solution

Create a small Reporting Truth boundary that derives durable, idempotent application read models from native lifecycle inputs and settlement results. Keep Nautilus as the sole live execution and position truth; keep immutable `system_events` and JSONL as audit/telemetry inputs rather than treating them as complete current-state or reporting ledgers.

The solution will:

- make sandbox account-equity fallback respect the configured runtime currency, including `pUSD`;
- introduce durable current-state projections for paper orders and positions;
- establish closed paper-trade results as the canonical leaderboard source;
- make daily reports revisable after late settlement and protected by a database-backed date/revision invariant;
- record external publish work durably before Telegram delivery and retry delivery without recreating settlement or report facts;
- report runtime health separately from SQLite storage health, with freshness semantics;
- centralize shared market parsing and Nautilus paper-event projection rules;
- narrow legacy compatibility and retired CLI surfaces so new code uses `MarketView`, explicit runtime modes, and shared boundaries;
- retain only the necessary observability persistence for each stream.

## User Stories

1. As a lab operator, I want a daily report to use the actual sandbox account balance, so that paper equity is not silently reset to its configured starting balance.
2. As a lab operator, I want `pUSD` to be recognized as the sandbox runtime currency, so that Sandbox execution and reporting use consistent financial semantics.
3. As a report reader, I want the displayed currency to be explicit, so that I do not confuse internal sandbox currency with an external USDC-denominated display.
4. As a report reader, I want a report to state when its data is incomplete, so that I do not mistake partial telemetry for a complete trading ledger.
5. As a runtime maintainer, I want best-effort telemetry to remain best-effort, so that observability pressure cannot silently redefine business facts.
6. As a dashboard user, I want each paper order to appear once in its latest lifecycle state, so that submitted and filled history is not mistaken for duplicate current orders.
7. As a dashboard user, I want each paper position to appear once in its latest lifecycle state, so that closed positions are not concurrently shown as open.
8. As a report reader, I want closed paper-trade results to be the canonical source of leaderboard statistics, so that dashboard and Telegram show the same PnL, win rate, and closed count.
9. As a dashboard user, I want leaderboard freshness and snapshot semantics to be clear, so that I know whether I am viewing live result projections or a daily snapshot.
10. As a lab operator, I want late settlement to mark the affected daily report as stale, so that a report does not permanently omit newly resolved trades.
11. As a lab operator, I want a revised report to have a deterministic revision identity, so that corrections are traceable and do not overwrite audit history ambiguously.
12. As a Telegram recipient, I want corrected reports to be identifiable as corrections, so that I can distinguish them from duplicate sends.
13. As a runtime maintainer, I want at most one active report revision per report date, so that overlapping scheduler runs cannot publish two independent reports for the same state.
14. As a runtime maintainer, I want the report-date invariant enforced by SQLite, so that correctness does not rely on a check-then-insert convention.
15. As a Telegram recipient, I want publish work to survive a process restart, so that a successfully created report can still be delivered after a transient failure.
16. As a runtime maintainer, I want report persistence to precede external publication, so that Telegram success cannot be followed by an invisible local failure and duplicate resend.
17. As a runtime maintainer, I want failed Telegram delivery to be retryable with an idempotency key, so that retries do not create duplicate notifications.
18. As a runtime maintainer, I want settlement facts to be persisted once, so that retrying audit or delivery side effects never creates a second paper-trade result.
19. As a runtime maintainer, I want settlement audit and publish completion tracked separately from settlement fact creation, so that a partial side-effect failure is recoverable.
20. As a dashboard user, I want runtime health to be `unknown` or `degraded` when no fresh runtime heartbeat exists, so that readable SQLite is not reported as a live trading runtime.
21. As a dashboard user, I want storage health and runtime health reported separately, so that I can diagnose whether the issue is persistence or the Nautilus process.
22. As a dashboard user, I want health payloads to include snapshot age and reason, so that stale state is actionable.
23. As a maintainer, I want dashboard routes to depend on a reporting read interface, so that UI code is not coupled directly to SQLite implementation details.
24. As a maintainer, I want application services to use public storage transactions, so that locking and connection management remain owned by the storage implementation.
25. As a maintainer, I want dashboard and Telegram to consume one paper-event projection contract, so that field aliases and derived quantities remain consistent.
26. As a maintainer, I want raw sparse Nautilus payload handling centralized, so that new event variants are adapted once rather than in every presentation consumer.
27. As a maintainer, I want readonly smoke checks to use production market parsing rules, so that smoke and market discovery cannot silently accept different Gamma payloads.
28. As a maintainer, I want a smoke test to validate shared parser behavior rather than a parallel parser, so that a public API contract change fails consistently.
29. As a runtime maintainer, I want high-frequency best-effort telemetry to have an explicit retention policy, so that SQLite and JSONL write load is proportional to its diagnostic value.
30. As a runtime maintainer, I want durable business facts distinguished from sampled or archived telemetry, so that storage costs and recovery expectations are clear.
31. As a runtime maintainer, I want the signal sidecar to use the runtime-owned publish lifecycle, so that Telegram connection, retry, and observability behavior have one owner.
32. As a maintainer, I want a single publish-service construction path, so that configuration and persistence behavior do not depend on the caller.
33. As an alpha developer, I want `MarketView` to be the normal public alpha input, so that new strategy code uses the current market data model.
34. As a test author, I want legacy `MarketSnapshot` adaptation explicitly marked as compatibility-only, so that historical fixtures do not become a production API commitment.
35. As an operator, I want runtime commands named explicitly as `nautilus`, `smoke`, or `dashboard`, so that command behavior is not inferred from incidental flags.
36. As an operator, I want any legacy `scheduler` invocation to be deterministic and visibly deprecated during migration, so that automation cannot choose a runtime mode unexpectedly.
37. As a reviewer, I want immutable event history retained separately from current-state projections, so that auditability is preserved without corrupting current UI state.
38. As a reviewer, I want no new local wallet, portfolio, matching, or position ledger introduced, so that the reporting redesign does not violate Nautilus ownership boundaries.
39. As a reviewer, I want Cache and native projections to remain the live runtime source, so that SQLite read models never drive execution decisions.
40. As a test author, I want report behavior verified through existing public scheduler, dashboard, and publish seams, so that tests validate user-visible outcomes rather than internal implementation choices.
41. As a test author, I want an account containing only `pUSD` covered by a regression test, so that the original equity fallback failure cannot recur.
42. As a test author, I want partial telemetry loss represented as an incomplete report condition, so that misleading report totals are not accepted as correct.
43. As a test author, I want multiple lifecycle events for one order and one position to reduce to one latest-state dashboard result, so that append-only history is never confused with current state.
44. As a test author, I want late settlement to create or select a newer report revision, so that report freshness is externally observable.
45. As a test author, I want duplicate scheduler attempts to produce one report claim and one delivery intent, so that concurrency behavior is safe.
46. As a test author, I want a publish failure after local report creation to remain pending and retryable, so that irreversible external delivery is not used as a transaction rollback mechanism.
47. As a test author, I want a missing or stale heartbeat to return non-`ok` runtime health while storage status stays visible, so that the health contract stays truthful.
48. As a test author, I want smoke and production discovery to agree on identical Gamma fixtures, so that parsing drift is detectable.
49. As a test author, I want both dashboard and publish output to use matching normalized values for the same Nautilus event, so that projection drift is detectable.
50. As a project maintainer, I want the implementation to remain SQLite-based and small, so that a lab project gains correctness without an unnecessary distributed event platform.

## Implementation Decisions

- Nautilus remains the sole owner of live market-data, execution, account, portfolio, and position truth. Reporting projections never submit, cancel, settle, or mutate native positions.
- Runtime currency is explicit at the reporting boundary. Account fallback selects the sandbox base currency rather than assuming the display-oriented `USDC` name.
- Immutable `system_events` remain audit history. They are not used directly as the current order or position view and are not assumed to be complete when produced by best-effort telemetry.
- Introduce a compact durable reporting read model with separate concepts for current order state, current position state, closed paper-trade results, report revisions, delivery intent/status, and runtime heartbeat status.
- Current-state reducers are keyed by stable paper order and paper position identifiers. Ordering is deterministic and based on lifecycle ordering metadata, not accidental query order.
- Closed `paper_trade_results` are the canonical input for leaderboard statistics. Daily reports may cache a dated snapshot but do not define a separate live leaderboard truth.
- Daily reports use an explicit revision or dirty/finalization policy. A late settlement affecting a report date marks the report eligible for recalculation rather than silently preserving an obsolete snapshot.
- SQLite enforces the report date/revision uniqueness invariant and supports an atomic report claim or upsert. The external publish path never relies on check-then-insert alone.
- A minimal SQLite outbox records a durable publish intent before Telegram delivery. Delivery attempts update independent status and use a deterministic idempotency key; no broker, distributed transaction coordinator, or event-sourcing framework is introduced.
- Settlement result creation is idempotent independently of JSONL and Telegram side effects. Audit and notification completion can be retried without reinserting the result.
- Dashboard health presents separate runtime and storage components. Missing or stale heartbeat is `unknown` or `degraded`, never synthetic runtime `ok`; the payload carries freshness age and cause.
- The dashboard consumes a narrow read/query port supplied by the composition root. The port may be SQLite-backed but UI routes must not depend on SQLite private details or raw schema-shaped event queries.
- Storage transactions, including any rollback or cleanup required by a durable operation, are public storage methods. Application services do not access connection or lock internals.
- A shared paper-event projector owns sparse native event aliasing, numeric conversion, identifiers, market metadata, and derived stake fields. Dashboard and publishing render its output.
- Readonly smoke reuses the production Gamma market parsing and matching boundary, adding only smoke-specific endpoint and readiness assertions.
- Best-effort telemetry retention is classified per stream. Query-required operational projections persist durably; high-frequency diagnostic telemetry is sampled, batched, rotated, or written to a single selected sink. Dual persistence is reserved for records whose audit value justifies it.
- The signal sidecar receives the runtime-owned publish service or a lifecycle-managed publisher factory instead of constructing Telegram infrastructure itself.
- `MarketSnapshot` conversion remains only in an explicitly named compatibility/test boundary. The normal alpha public surface accepts `MarketView`.
- Runtime mode parsing converges on explicit modes. If a temporary `scheduler` compatibility command remains, it has one deterministic target, emits a deprecation warning, and has an announced removal path.

## Testing Decisions

Good tests assert visible contract behavior: report values, report revision and delivery state, dashboard response payloads, health semantics, public smoke results, and explicit CLI behavior. They must not assert private locks, raw SQL strings, implementation-specific event loops, or the internal shape of a reducer beyond its observable result.

The approved existing testing seams are:

1. **Scheduler reporting and settlement seam.** Use the existing scheduler/report generation and settlement-check entry points with temporary SQLite state, controlled Nautilus Cache/Portfolio projections, and fake publishers. Verify `pUSD` equity, incomplete-data signaling, late settlement revision, one-report claim behavior, and retryable delivery state.
2. **Dashboard HTTP seam.** Use the existing dashboard application/router with a temporary reporting store and invoke public endpoints. Verify latest order/position state, canonical leaderboard behavior, and distinct storage/runtime health with heartbeat freshness.
3. **Publishing persistence seam.** Use the existing `PublishService` boundary with a deterministic fake Telegram publisher and persistent temporary storage. Verify durable publish intent precedes send, retries are idempotent, and settlement/report facts are not duplicated when side effects fail.

Additional focused contract tests may cover readonly smoke against shared Gamma parser fixtures and CLI command parsing, but they should remain black-box public API/CLI tests.

Existing reporting-cache, trading-node runtime, persistence service, storage reporting/publish, market universe, readonly smoke, and CLI runtime mode tests are prior art. New tests should extend those behavioral patterns and avoid adding parallel test harnesses.

## Out of Scope

- Replacing NautilusTrader execution, Cache, Portfolio, RiskEngine, DataEngine, or native order lifecycle.
- Building a local matching engine, wallet ledger, portfolio ledger, or position ledger.
- Using SQLite, JSONL, Gamma, RTDS, or chain settlement information to mutate native Nautilus execution state.
- Introducing Kafka, Redis streams, a distributed transaction coordinator, a general event-sourcing framework, or a new database.
- Redesigning strategies, alpha formulas, `DecisionPolicy`, `MarketView` assembly, or the completed Issue #1 runtime cutover.
- Removing every historical fixture or compatibility helper immediately; only public exposure and new production use are constrained.
- Broad reformatting or unrelated refactors.

## Further Notes

This specification intentionally groups P0/P1 reporting correctness with closely related P2 boundary cleanup because the latter prevents the former from fragmenting into multiple incompatible projection paths. Implementation should still be sequenced: first currency correctness and report/health truth, then durable delivery/revision semantics, then duplicate parser/projector and compatibility cleanup.

The project is not production, so the preferred design is a small SQLite-backed projection and outbox, not operationally heavy infrastructure. Simplicity does not permit misleading reporting: when data is unavailable or incomplete, the system should expose that state explicitly.

Issue #1 remains complete and excluded from this work. This specification must preserve its established ownership boundary: Nautilus Runtime Truth, PolySignal Decision Truth, and Reporting Truth remain distinct.
