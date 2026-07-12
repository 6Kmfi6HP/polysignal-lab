## Problem Statement

PolySignal Lab has already migrated the live trading path onto NautilusTrader 1.229.0: `TradingNode` owns lifecycle, market data, execution, cache, portfolio, and sandbox fills; PolySignal owns alpha decisions, market identity, signal policy, market rotation, and report projections. Architecture review after remediation confirms there is no second execution truth.

The remaining problem is not correctness of the Nautilus ownership model. It is incomplete cutover:

- A thick `PolySignalNativeStrategy` facade still concentrates multi-step orchestration after partial extraction.
- Assembler books still bootstrap through an empty provider and are mutated onto Cache after node build.
- Legacy OrderBook / CLOB REST-WS projection surfaces remain in-tree and can still be mistaken for live runtime authority.
- Naming still implies old models (`DecisionPolicyActor`, paper-era vocabulary) and confuses ownership reviews.
- Historical migration docs and dual-path helpers continue to inflate cognitive load in a non-production codebase that no longer needs compatibility-preserving half-measures.

Because this project is not production-bound, the right move is not more compatibility patching. It is a deliberate architecture cutover: keep the correct Nautilus core, delete dual-path residue, thin the Strategy host, and make the three ownership truths explicit and enforceable.

## Solution

Perform a non-production architecture cutover that leaves exactly three truths:

1. **Nautilus Runtime Truth** — instruments, books/ticks, orders/fills, positions/accounts/portfolio, sandbox execution lifecycle.
2. **PolySignal Decision Truth** — market business identity, alpha, signal gate, arbitration/consensus, entry/exit policy, spot/PTB domain projection.
3. **Reporting Truth** — SQLite/JSONL/Telegram/dashboard projections that never drive trading state.

Concretely:

- Keep Nautilus as the only execution and live book authority.
- Make MarketView assembly Cache-backed from construction time; delete empty-book bootstrap mutation.
- Keep Strategy as a thin Nautilus callback host; push remaining multi-step orchestration into existing collaborators.
- Rename pure decision policy away from Actor vocabulary while preserving shared gate/arbiter/consensus ownership.
- Quarantine or delete legacy OrderBook/CLOB dual-stack surfaces so they cannot re-enter the live decision path.
- Archive historical migration docs and replace them with two living boundary documents.
- Enforce the cutover with three existing high-level seams rather than inventing a new framework.

This is an ownership and maintainability cutover, not a feature rewrite and not a settlement/reconciliation expansion.

## User Stories

1. As a runtime owner, I want TradingNode to remain the only lifecycle host, so that PolySignal never reintroduces a second orchestrator.
2. As a runtime owner, I want DataEngine and ExecutionEngine to own market-data and order lifecycle, so that project code only reacts to Nautilus events.
3. As a runtime owner, I want Cache to be the only live book and trade-tick authority, so that MarketView never depends on a local order-book registry.
4. As a runtime owner, I want Portfolio/Position/Account state to come only from Nautilus, so that reports cannot invent open positions.
5. As a strategy developer, I want `PolySignalNativeStrategy` to be a thin callback host, so that I can find business logic in focused collaborators instead of a 700-line facade.
6. As a strategy developer, I want custom-data routing to live outside the Strategy facade, so that on_data remains a pure ingress point.
7. As a strategy developer, I want market-data condition mapping to live outside the Strategy facade, so that quote/trade/book callbacks stay thin.
8. As a strategy developer, I want decision pipeline orchestration to remain a shared collaborator, so that entry evaluation is not reimplemented per strategy.
9. As a strategy developer, I want order and position event projection to remain a shared collaborator, so that reporting hooks do not bloat Strategy methods.
10. As a strategy developer, I want subscription lifecycle to remain a shared collaborator, so that instrument subscribe/unsubscribe logic is not duplicated.
11. As a decision-policy owner, I want a pure DecisionPolicy service with no Nautilus imports, so that gate/arbiter/consensus can be unit-tested without framework ceremony.
12. As a decision-policy owner, I want shared policy injection to remain mandatory, so that strategies cannot create private gate/arbiter instances.
13. As a decision-policy owner, I want the optional Nautilus Actor wrapper to remain thin, so that Actor lifecycle is not confused with business policy ownership.
14. As a market-data owner, I want RTDS spot transport to remain a LiveDataClient path, so that managed spot never bypasses DataEngine.
15. As a market-data owner, I want sidecar CustomData and RTDS spot to remain client-id separated, so that DataEngine routing stays deterministic.
16. As a market-data owner, I want MarketRotationActor to publish universe/metadata/PTB CustomData without republishing spot, so that single-source spot ownership is preserved.
17. As a market identity owner, I want MarketCatalog to remain the condition/token business-key boundary, so that instrument resolution stays centralized.
18. As an alpha developer, I want MarketViewAssembler to assemble immutable MarketView from Cache books plus CustomData, so that alpha never talks to venue transports directly.
19. As an alpha developer, I want MarketView assembly to fail closed when books are unavailable, so that stale or empty bootstrap state cannot produce silent decisions.
20. As an order-routing owner, I want ApprovedDecision mapping to remain a thin native order gateway, so that order_factory and submit_order stay the only submission path.
21. As an order-routing owner, I want Side UP/DOWN and OrderIntent to remain domain vocabulary, so that prediction-market semantics are not flattened incorrectly into OrderSide/TimeInForce.
22. As a risk owner, I want project pre-trade constraints to read Cache open state rather than invent local portfolio state, so that risk overlays do not become a second ledger.
23. As an exit-policy owner, I want reduce-only exits to be derived from Cache positions, so that exits remain strategy-local decisions under Nautilus lifecycle.
24. As a settlement owner, I want settlement to remain report-only under Nautilus 1.229.0, so that the system never fabricates payout fills or PositionClosed events.
25. As a reporting owner, I want SQLite/JSONL/Telegram/dashboard to consume projections only, so that observability cannot mutate runtime trading truth.
26. As a dashboard consumer, I want legacy book consumers either migrated to Cache projections or quarantined, so that I am never taught a second live book path.
27. As a maintainer, I want legacy OrderBookRegistry and standalone CLOB clients blocked from runtime/decision imports, so that dual-path regressions fail in CI.
28. As a maintainer, I want historical migration docs archived, so that stale “current state” claims stop driving design decisions.
29. As a maintainer, I want two living docs for architecture and runtime boundary, so that new work has one authoritative ownership map.
30. As a maintainer, I want DecisionPolicyActor renamed to DecisionPolicy, so that reviews stop misclassifying pure policy as a Nautilus Actor or RiskEngine.
31. As a maintainer, I want paper-era runtime vocabulary reduced or renamed where it implies local execution truth, so that sandbox ownership stays obvious.
32. As a maintainer, I want EmptyBookDataProvider deleted or made unreachable, so that post-build assembler mutation is no longer part of composition.
33. As a maintainer, I want node composition to construct Cache-backed books once after cache exists, so that MarketView wiring is deterministic.
34. As a test author, I want existing Nautilus smoke and boundary seams reused, so that cutover verification does not invent a new test framework.
35. As a test author, I want safety scan rules to encode the cutover forbid-list, so that dual execution truth and legacy reattachment fail fast.
36. As a test author, I want decision-policy behavior preserved across rename, so that gate/arbitration regressions are caught without rewriting product logic.
37. As a test author, I want strategy exit and order submission behavior preserved while the facade thins, so that extraction cannot silently change runtime outcomes.
38. As an integrator, I want sandbox defaults to remain paper-safe and L2-aligned with the current runtime, so that cutover does not reopen live execution.
39. As an integrator, I want optional Nautilus dependency boundary preserved, so that default Python 3.11 install stays free of hard Nautilus imports where intended.
40. As a future agent implementer, I want this cutover fully specified with ready-for-agent status, so that implementation can proceed without rediscovering architecture intent.
41. As a future agent implementer, I want out-of-scope items explicit, so that settlement authority, live trading, and speculative frameworks are not invented during implementation.
42. As a project owner of a non-production lab, I want aggressive deletion of compatibility residue, so that cognitive load drops without waiting for production deprecation windows.
43. As a project owner, I want no second matching engine, wallet ledger, or reverse instrument registry, so that Nautilus ownership remains absolute.
44. As a project owner, I want change amplification reduced around Strategy/Actor hubs, so that future alpha work is surgical rather than facade-wide.
45. As a reviewer, I want confirmed false positives documented, so that high CBO/LCOM metrics alone are not treated as ownership failures.
46. As a reviewer, I want accepted boundaries preserved, so that MarketCatalog, MarketView, SignalGate, native_order mapping, and report-only settlement are not “fixed” incorrectly.
47. As a runtime operator in lab mode, I want fail-closed behavior when required projections or books are missing, so that incomplete wiring cannot look healthy.
48. As a runtime operator, I want market discovery/rotation to remain project-owned business logic on an Actor timer path, so that venue adapters are not overloaded with PolySignal universe rules.
49. As a documentation consumer, I want archive paths clearly marked historical, so that pre-cutover claims are not reused as current requirements.
50. As a safety owner, I want import and symbol forbid rules to cover live Polymarket execution and local execution simulators, so that cutover cannot accidentally re-enable unsafe paths.

## Implementation Decisions

### Ownership model
- Preserve the locked NautilusTrader 1.229.0 API surface as the only runtime authority for instruments, books, orders, fills, positions, accounts, portfolio, and sandbox execution.
- Preserve PolySignal ownership of market discovery/rotation, MarketCatalog business keys, alpha decisions, DecisionPolicy (gate/arbiter/consensus), spot/PTB domain projection, and reporting projections.
- Preserve report-only settlement. No fabricated native settlement mutation is allowed under 1.229.0.
- Do not introduce a second orchestrator, matching engine, wallet ledger, reverse instrument registry, or dynamic runtime class factory.

### Three-truth cutover target
- **Runtime truth:** TradingNode composition, official Polymarket data client, sandbox execution client, RTDS LiveDataClient, Cache-backed market data provider, thin Strategy/Actor hosts.
- **Decision truth:** MarketCatalog, MarketView assembly, alpha cores, DecisionPolicy, native order mapping, reduce-only exit policy, project pre-trade constraints over Cache.
- **Reporting truth:** event projections, SQLite/JSONL persistence, Telegram/dashboard consumers, settlement report projection.
- Any module that is not one of these three either moves into a collaborator of one truth or is quarantined/deleted.

### Node composition / MarketView wiring
- Delete empty-book bootstrap as a live composition path.
- Construct MarketView books provider only after Nautilus cache is available, or inject a single cache-backed provider before strategies evaluate.
- MarketViewAssembler remains a pure projection over catalog + book provider + custom data.
- Fail closed when books are unavailable; do not fall back to OrderBookRegistry.
- Keep SIDECAR and RTDS client-id separation already established; do not republish RTDS spot through market rotation.

### Strategy thinning
- Keep Strategy as the Nautilus callback host.
- Freeze growth of multi-step business methods on the Strategy facade.
- Move remaining multi-step orchestration into existing collaborators: custom data handling, data boundary/condition mapping, decision pipeline, order/position event projection, subscriptions, native order gateway, exit policy, observability hooks.
- Do not invent a second Strategy hierarchy or generic framework layer.

### Decision policy rename and shape
- Rename pure shared policy away from Actor vocabulary (DecisionPolicy).
- Keep the optional thin Nautilus Actor adapter only if runtime registration still needs it.
- Preserve mandatory shared policy injection.
- Preserve SignalGate / arbiter / consensus as business policy, not RiskEngine replacement.
- Preserve Side and OrderIntent as domain vocabulary with thin enum mapping into Nautilus order types.

### Legacy dual-path retirement
- Treat domain OrderBook, OrderBookRegistry, and standalone CLOB REST/WS clients as non-live residue.
- Block runtime/decision/trading paths from importing them.
- Migrate remaining dashboard/smoke consumers to Cache projections or explicit non-live adapters where needed.
- If short-term consumers remain, quarantine them under an explicit legacy surface with import guards rather than leaving them ambiently available.
- Do not delete reporting capabilities that still need read-only projections; delete only the dual-truth interpretation and runtime reachability.

### Documentation cutover
- Archive historical migration/review docs that describe superseded current-state claims.
- Maintain two living documents only:
  - architecture ownership and dependency direction
  - runtime boundary, forbid-list, sandbox/report-only constraints
- Record accepted boundaries and false-positive traps so future reviews do not re-litigate correct designs.

### Non-production posture
- Prefer deletion and renaming over compatibility shims.
- Prefer fail-fast composition over transitional defaults.
- Keep optional Nautilus dependency boundary unless a later explicit decision makes Nautilus a hard install requirement.
- Keep paper-safe sandbox defaults; do not expand into live Polymarket execution.

### Testing seams (approved)
Use three existing high-level seams only:

1. **Node composition seam**
   - Highest seam for wiring truth.
   - Verifies TradingNode assembly yields Cache-backed MarketView books.
   - Verifies no empty-provider bootstrap remains on the live path.
   - Reuses full paper runtime / node / trading-node runtime tests as the primary harness.

2. **Safety / import boundary seam**
   - Highest seam for dual-path prevention.
   - Extends existing safety scan / dependency boundary / platform boundary tests.
   - Forbids legacy OrderBook/CLOB reattachment into runtime/decision/trading.
   - Forbids second execution truth symbols and settlement mutation patterns already blocked by project safety rules.

3. **Decision + strategy behavior seam**
   - Highest seam for behavioral preservation during rename/extraction.
   - Reuses decision-policy, strategy-base, native-order, and native-exit tests.
   - Verifies DecisionPolicy rename, shared injection, gate/arbitration outcomes, order submission mapping, and reduce-only exits remain externally equivalent.

No additional architectural seams are introduced for this cutover.

## Testing Decisions

### What makes a good test here
- Test external behavior and ownership outcomes, not private helper topology.
- Prefer existing Nautilus integration and boundary tests over new low-level unit scaffolding.
- Assert “who owns truth” and “what is unreachable,” not line counts or LCOM scores.
- Preserve current product behavior for gate, order mapping, exits, and report-only settlement while structure changes.
- Fail closed on dual-path regressions.

### Modules / surfaces under test
- Node composition and runtime wiring
- MarketView assembly book provider attachment
- Safety scan / dependency boundary forbid rules
- DecisionPolicy public behavior after rename
- Strategy external behavior after facade thinning
- Native order gateway and reduce-only exit behavior
- Settlement report-only markers and non-mutation guarantees where already covered

### Prior art to reuse
- Full paper runtime smoke and trading-node runtime tests for composition
- Node / runtime config tests for wiring defaults
- Safety boundary and dependency boundary tests for forbid-lists
- Decision policy tests for gate/arbitration behavior
- Strategy base / static native strategy tests for callback host behavior
- Native order and native exit tests for submission and reduce-only outcomes
- Cache market data and market view assembler tests for Cache projection behavior
- Sidecar / RTDS client routing tests for client-id separation

### Acceptance criteria
- Live MarketView path reads Cache-backed books only.
- Empty-book bootstrap is gone from live composition or proven unreachable.
- Runtime/decision/trading cannot import legacy OrderBookRegistry or standalone CLOB clients.
- DecisionPolicy rename preserves shared injection and external decision outcomes.
- Strategy thinning preserves order submission and reduce-only exit external behavior.
- Settlement remains report-only with no Cache/Portfolio/Position mutation path.
- Existing core Nautilus regression set and safety scan remain green.

## Out of Scope

- Live Polymarket execution enablement
- Implementing native prediction-market settlement/redeem authority not present in Nautilus 1.229.0
- Replacing sandbox execution with a custom matching engine or wallet ledger
- Broad dashboard UX redesign unrelated to data-source ownership
- Alpha strategy formula changes
- Telegram product redesign
- Full package rename of the entire repository in one step if not required for ownership enforcement
- Chasing CBO/LCOM metrics for their own sake
- Redis restart-continuity claims without real smoke verification
- Building a new multi-agent framework, command bus, or generic plugin system
- Changing locked Nautilus version away from 1.229.0 as part of this cutover

## Further Notes

### Confirmed architecture scorecard from post-refactor review
- Ownership conformance is strong after remediation.
- Residual debt is maintainability and dual-path residue, not missing Nautilus engines.
- High CBO/LCOM on Strategy/Actor/policy hubs is often framework-shaped or desirable fan-in; do not treat metrics alone as defects.

### Accepted boundaries that must not be “fixed”
- MarketCatalog business-key boundary
- MarketViewAssembler domain projection
- Side UP/DOWN vs OrderSide
- OrderIntent vs TimeInForce
- native_order thin mapping
- SignalGate / consensus / arbitration
- report-only settlement
- optional Nautilus imports
- RTDS LiveDataClient single-source spot transport
- NativeExitPolicy over Cache positions

### Suggested implementation order
1. Living architecture + runtime boundary docs; archive historical migration claims.
2. Node composition cutover: Cache-backed books only; remove empty-provider live path.
3. Safety/import forbid rules for legacy dual-path reattachment.
4. DecisionPolicy rename with behavior-preserving tests.
5. Strategy facade thinning into existing collaborators.
6. Legacy OrderBook/CLOB quarantine or deletion once consumers are migrated or isolated.
7. Final smoke + safety scan verification.

### Non-production bias
This project can delete aggressively. Prefer honest names, fail-fast wiring, and fewer modules over compatibility layers. Keep verification, but do not keep dual truths.
