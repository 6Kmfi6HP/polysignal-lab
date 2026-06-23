# 09 Strategy Execution Order Optimization Design

**Status:** Approved
**Scope:** One standalone architecture change. Execute only after earlier targeted specs (01-08) have stabilized; do not batch with them.
**Goal:** Optimize strategy execution ordering, introduce deterministic scheduling priorities, and enable safe concurrency for read-only snapshot building and strategy evaluations.

## Problem

PolySignal Lab currently runs a single-threaded scheduler path. `evaluate_once()` builds one market snapshot at a time, evaluates every loaded strategy against that snapshot, then immediately mutates gate and consensus state for each candidate. The run loop later processes the accepted list through paper simulation, resting-order ticks, settlements, reports, and state persistence in sequence. This flow has several limitations:
1. **No Dependency Management**: Strategies cannot declare execution dependencies (e.g., "Strategy A must run before Strategy B").
2. **Poor Performance**: Async Price-To-Beat checks and snapshot construction execute serially, capping loop frequency under multiple active markets.
3. **Implicit Priority**: YAML configuration sequence implicitly defines priority for signal deduplication, rate limit, consensus generation, and wallet cash reservation. A minor change in configuration placement alters production trading behavior.
4. **Cross-Market Limits**: Cross-market strategies such as `CrossMarketBotStrategy` only see one market's snapshot at a time inside their current `evaluate()` loop. Evaluating relation legs independently without a synchronized multi-market context can create false signals, missed baskets, or order-dependent repair behavior.

## Non-goals

- No Redis/Kafka or external worker pool adoption in this spec.
- No live trading, order placement, or authenticated CLOB writes.
- No full rewrite of existing strategy alpha logic; a cross-market coordinator may add an adapter/context method for relation-level evaluation.
- No changes to the existing scheduler CLI options.

## Target behavior

1. **YAML Strategy Metadata**: Strategy configurations specify explicit execution metadata: `priority`, `depends_on`, and `execution_mode`.
2. **Topological Sorting**: Strategy dependencies form a Directed Acyclic Graph (DAG) validated at startup using Python standard library `graphlib.TopologicalSorter` to reject cycle loops.
3. **Execution Pipeline Stages**: The scheduler loop is split into distinct stages:
   - **Parallel Snapshot Building**: Build market snapshots with bounded concurrency.
   - **Cross-Market Coordination**: Group snapshots for every configured relation before calling cross-market evaluation.
   - **Scheduled Strategy Evaluation**: Run independent `stateless` strategy tasks in parallel ready-sets, and evaluate `stateful` strategies sequentially per strategy instance.
   - **Signal Arbitration**: Apply non-mutating conflict resolution and stable ordering before the stateful gate/consensus/paper phase.
   - **Serial Commit Phase**: Run gate, authoritative dedupe/rate limits, consensus, persistence, publishing, and paper simulation in a strictly ordered sequence on the main loop thread.
4. **Parallel Evaluation Isolation**: Strategy evaluation tasks run in isolated try/except blocks. A single strategy throwing an exception must not crash the cycle.
5. **Determinism**: Concurrently evaluated candidates are stable-sorted by `(strategy_priority, strategy_config_index, market_config_index, candidate_index)` before any mutable gate, consensus, or paper state changes occur.

## Current-state constraints

- `StrategyConfig` currently has `extra="forbid"`, and each concrete strategy config model owns its own fields. Implementation must add execution metadata through a shared base/mixin accepted by every strategy config, or through a sibling metadata map, so YAML `priority`/`depends_on`/`execution_mode` does not break validation.
- `SignalGate.evaluate()` mutates `SignalDeduper` and `ChannelRateLimiter`; `ConsensusEngine.add()` mutates its in-memory buffer. These operations are not safe inside parallel workers and must remain in the serial commit phase unless they are redesigned as pure preflight plus ordered commit.
- `PaperSimulator.process_signal()` and `PaperWallet.apply_fill()` mutate cash, exposure, positions, passive orders, and strategy fill callbacks. They remain single-writer in this spec.
- Existing strategy instances are mostly stateful. `execution_mode="stateless"` is opt-in only after tests prove the strategy has no mutable evaluation state.
- `BaseStrategy.evaluate()` is synchronous today. Concurrent strategy evaluation must use an explicit bounded executor path (for example `asyncio.to_thread`) only for opt-in stateless strategies, or be deferred until an async strategy API exists.

## Proposed interfaces

### Strategy Metadata Config

```python
class StrategyExecutionConfig(BaseModel):
    priority: int = 100  # Lower number = higher priority
    depends_on: list[str] = Field(default_factory=list)
    execution_mode: Literal["stateless", "stateful", "cross_market"] = "stateful"
```

### Strategy Configuration Mapping

Use a nested `execution` block under each concrete strategy config. This avoids name collisions with strategy-specific fields and gives every model one shared metadata shape:

```yaml
strategies:
  ptb_diff:
    enabled: true
    execution:
      priority: 30
      depends_on: []
      execution_mode: stateless
    # other config...
  late_consensus:
    enabled: true
    execution:
      priority: 50
      depends_on: []
      execution_mode: stateful
  cross_market_bot:
    enabled: true
    execution:
      priority: 10
      depends_on: []
      execution_mode: cross_market
```

Every strategy config model must inherit or compose this field with a default. If the field is omitted, the migration preserves current behavior: priority defaults to `100`, dependencies default to empty, execution mode defaults to `stateful`, and YAML strategy key order remains the tie-breaker.

### Coherent Snapshot Batch

```python
@dataclass(frozen=True, slots=True)
class SnapshotBatch:
    batch_id: str
    as_of: datetime
    market_order: tuple[str, ...]
    snapshots: dict[str, MarketSnapshot]
    max_source_skew_ms: int
```

The snapshot stage creates one batch id and one scheduler-level `as_of` time per evaluation cycle. Each `MarketSnapshot` still carries its own source timestamps/freshness, but relation-level evaluation must reject or audit any cross-market group whose leg snapshots exceed the configured `max_source_skew_ms`.

### Cross-Market Evaluation Context

```python
@dataclass(frozen=True, slots=True)
class CrossMarketEvaluationContext:
    relation_id: str
    snapshots_by_condition_id: dict[str, MarketSnapshot]
    batch: SnapshotBatch


class CrossMarketStrategy(Protocol):
    name: str

    def evaluate_group(
        self, context: CrossMarketEvaluationContext
    ) -> list[SignalCandidate]: ...
```

The scheduler dispatches `execution_mode="cross_market"` strategies through `evaluate_group()` or a coordinator-owned adapter. It must not call the existing single-market `evaluate(snapshot)` path for relation-level decisions.

### Signal Arbiter

```python
class SignalArbiter:
    def __init__(self, conflict_policy: str = "suppress_ambiguous"):
        self.conflict_policy = conflict_policy

    def arbitrate(
        self,
        candidates: list[SignalCandidate],
        strategy_priorities: dict[str, int],
        strategy_config_indexes: dict[str, int],
        market_config_indexes: dict[str, int],
    ) -> list[SignalCandidate]:
        """Resolves conflicts and stable-sorts candidates without mutating gate state."""
        pass
```

## Acceptance criteria

- `PolySignalScheduler` validates strategy dependencies at startup and raises `CycleError` on dependency cycles before the run loop starts.
- Snapshot building and explicitly `stateless` strategy evaluations can be exercised with bounded concurrency in tests using fake delays or blocking synchronous fakes run through the chosen executor path.
- Parallel phases do not change deduplication, gating, consensus, paper-order, paper-fill, wallet, or persistence results compared to equivalent serial ordering.
- Cross-market strategy evaluation receives all relation legs from one `SnapshotBatch` and rejects/audits incoherent legs whose source skew exceeds the configured threshold.
- An exception thrown in a strategy job is logged and isolated to that job; the cycle continues for remaining strategies.
- Resting order ticks, settlements, report generation, and state persistence continue after the serial signal commit phase in the existing run-loop order.

## Test strategy

- **DAG Verification**: Create tests asserting `TopologicalSorter` correctly registers strategy dependencies, checks execution levels, and raises `CycleError` on cyclic dependency loops.
- **Arbiter Conflict Tests**: Assert that `SignalArbiter` suppresses conflicting `UP`/`DOWN` signals on the same market and orders output candidates by stable priority without calling mutable gate/deduper state.
- **Concurrency Test**: Use synchronous blocking fake `evaluate()` implementations for strategies and verify that explicitly stateless strategies run through the chosen bounded executor/concurrency path while stateful strategies run sequentially per strategy instance.
- **Equivalence Test**: Verify that serial execution vs parallel evaluation plus ordered commit produce identical accepted signals, rejected-signal records, consensus signals, paper orders, fills, positions, and cash states on identical data feeds.

## Rollout

1. Add YAML config schema validation and the DAG scheduler setup.
2. Implement the `SignalArbiter` with conflict resolution and deterministic sorting.
3. Refactor `evaluate_once()` to split snapshot building, evaluation, arbitration, and serial commits.
4. Implement async parallel snapshot building and stateless strategy evaluation.
5. Integrate multi-leg snapshot coordination for `CrossMarketBot`.
