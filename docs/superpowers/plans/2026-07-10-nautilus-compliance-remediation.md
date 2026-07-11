# Nautilus Compliance Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the confirmed Nautilus compliance blockers without creating a second execution runtime or weakening the Python 3.11 optional-dependency boundary.

**Architecture:** Keep the existing `LiveNode`/`Strategy`/`DecisionPolicyActor` architecture. Retire the legacy runtime entry point, restore alpha/runtime separation, make grouped policy evaluation deterministic and pair-safe, convert replay timestamps strictly, and refuse actor-thread crypto-price I/O. Each change receives a focused regression test before implementation and shares no speculative framework.

**Tech Stack:** Python 3.11–3.14, NautilusTrader optional extra, pytest, uv, Ruff, shell entrypoint, existing `DecisionPolicyActor` and `MarketRotationActor`.

## Global Constraints

- Do not modify `@refs/` or `docs/nautilus_reference/`.
- Default Python 3.11 install and `import polysignal_lab`/`import polysignal_lab.alpha` must not import NautilusTrader.
- Default execution is Nautilus sandbox only; never register authenticated Polymarket execution.
- Nautilus retains ownership of lifecycle, Cache, Portfolio, order state, fills, positions, DataEngine, and ExecutionEngine.
- SQLite, JSONL, Telegram, and dashboard remain downstream projections only.
- Alpha modules must not import runtime or Nautilus-specific types.
- Replay-sensitive time comes from valid event timestamps, never ambient wall-clock fallback.
- Arbitration failures must fail closed and produce degradation evidence.
- Preserve pre-existing user changes outside each task; no commit/push unless separately requested.

---

## File Structure

- `docker-entrypoint.sh`: selects safe runtime mode only.
- `tests/test_docker_entrypoint.py` (new): subprocess-free assertions for entrypoint mode routing.
- `src/polysignal_lab/alpha/__init__.py`: host-agnostic alpha exports only.
- `src/polysignal_lab/nautilus_runtime/order_plan.py`: runtime-local order-plan type.
- `tests/test_nautilus_dependency_boundary.py`: default import boundary checks.
- `src/polysignal_lab/nautilus_runtime/decision_policy.py`: eligibility-aware group arbitration contract.
- `src/polysignal_lab/nautilus_runtime/native_strategy.py`: fail-closed use of group arbitration.
- `src/polysignal_lab/nautilus_runtime/strategy/decision_pipeline.py`: explicit group result plumbing if required.
- `tests/test_nautilus_decision_policy.py`, `tests/test_nautilus_strategy_base.py`, `tests/test_alpha_pre_order_market.py`: arbitration and paired-order regressions.
- `src/polysignal_lab/nautilus_runtime/strategy/event_projection.py`: strict event timestamp conversion.
- `src/polysignal_lab/nautilus_runtime/strategy/helpers.py`: shared strict timestamp helper or its removal after relocation.
- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`: event-derived view clock contract.
- `src/polysignal_lab/alpha/dump_hedge_core.py`, `low_side_dual_reversion_core.py`, `pre_order_market_core.py`: logical-clock-only alpha behavior.
- `tests/test_nautilus_projections.py`, `tests/test_nautilus_market_view_assembler.py`, alpha tests: timestamp and replay regressions.
- `src/polysignal_lab/nautilus_runtime/market_rotation.py`: no actor-thread crypto-price fallback.
- `tests/test_nautilus_market_rotation.py`: native actor configuration and no-I/O regression.
- `src/polysignal_lab/alpha/vwap_trade_history.py`: immutable snapshot return values.

---

### Task 1: Retire legacy Docker execution default

**Files:**
- Modify: `docker-entrypoint.sh:7-33`
- Create: `tests/test_docker_entrypoint.py`

**Interfaces:**
- Consumes: positional mode selector `${1:-...}`.
- Produces: no argument → `--mode nautilus`; `scheduler` → exit code `2` without `python -m`; supported operational modes keep their existing commands.

- [ ] **Step 1: Write failing entrypoint behavior tests**

```python
from pathlib import Path


def _script() -> str:
    return Path("docker-entrypoint.sh").read_text(encoding="utf-8")


def test_entrypoint_defaults_to_nautilus() -> None:
    source = _script()
    assert 'case "${1:-nautilus}" in' in source
    assert "--mode nautilus" in source


def test_entrypoint_retires_scheduler_execution_mode() -> None:
    source = _script()
    scheduler = source.split("scheduler)", 1)[1].split(";;", 1)[0]
    assert "retired" in scheduler.lower()
    assert "python -m polysignal_lab.app.main" not in scheduler
    assert "exit 2" in scheduler
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/test_docker_entrypoint.py -v`

Expected: failure because the entrypoint defaults to `scheduler` and launches `app.main`.

- [ ] **Step 3: Apply the minimal entrypoint change**

```bash
case "${1:-nautilus}" in
  scheduler)
    echo "[entrypoint] scheduler execution mode is retired; use nautilus"
    exit 2
    ;;
  nautilus)
    echo "[entrypoint] Starting PolySignal Lab on Nautilus runtime..."
    exec python -m polysignal_lab.app.main --mode nautilus --config config/signal_bot.yaml
    ;;
```

Retain the existing dashboard, test, smoke, shell, and unknown-mode cases. Update the usage string to identify `scheduler` as retired or remove it from accepted choices.

- [ ] **Step 4: Run task verification**

Run: `uv run pytest tests/test_docker_entrypoint.py -v`

Expected: PASS.

---

### Task 2: Restore the Python 3.11 alpha dependency boundary

**Files:**
- Modify: `src/polysignal_lab/alpha/__init__.py:37-66`
- Modify: `tests/test_alpha_types.py:95-150` only for direct runtime import
- Modify: `tests/test_nautilus_dependency_boundary.py:23-49`

**Interfaces:**
- Consumes: `OrderSubmissionPlan` only inside `nautilus_runtime`.
- Produces: `polysignal_lab.alpha` exports no `NautilusOrderSpec`; direct consumers import `OrderSubmissionPlan` or compatibility alias from `nautilus_runtime.order_plan`.

- [ ] **Step 1: Add the failing import-boundary assertion**

```python
def test_alpha_package_import_does_not_require_nautilus() -> None:
    sys.modules.pop("nautilus_trader", None)
    sys.modules.pop("polysignal_lab.alpha", None)

    module = importlib.import_module("polysignal_lab.alpha")

    assert module is not None
    assert "nautilus_trader" not in sys.modules
    assert not hasattr(module, "NautilusOrderSpec")
```

- [ ] **Step 2: Confirm the clean Python 3.11 repro fails**

Run: `uv run --python 3.11 python -c 'import polysignal_lab.alpha'`

Expected: `ModuleNotFoundError: No module named 'nautilus_trader'`.

- [ ] **Step 3: Remove the runtime re-export**

Delete only:

```python
from polysignal_lab.nautilus_runtime.order_plan import NautilusOrderSpec
```

and its `__all__` member from `alpha/__init__.py`. Keep `NautilusOrderSpec = OrderSubmissionPlan` solely in `nautilus_runtime/order_plan.py` while compatibility is required. Tests that construct it import directly from runtime.

- [ ] **Step 4: Verify default and runtime paths**

Run:

```bash
uv run --python 3.11 python -c 'import polysignal_lab.alpha'
uv run pytest tests/test_alpha_types.py tests/test_nautilus_dependency_boundary.py -v
```

Expected: all pass without adding Nautilus to the Python 3.11 environment.

---

### Task 3: Make paired decision arbitration safe and fail closed

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/decision_policy.py:208-308`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:392-410`
- Modify only if needed: `src/polysignal_lab/nautilus_runtime/strategy/decision_pipeline.py:107-173`
- Test: `tests/test_nautilus_decision_policy.py`
- Test: `tests/test_nautilus_strategy_base.py`
- Test: `tests/test_alpha_pre_order_market.py`

**Interfaces:**
- Consumes: `list[tuple[AlphaDecision, MarketView]]` from one core evaluation boundary.
- Produces: an ordered set of eligible decisions: same non-empty `pair_id` members survive together; only non-paired, prevalidated candidates enter ambiguity suppression; exception produces zero survivors and a degradation signal.

- [ ] **Step 1: Add failing decision-policy tests**

Add fixtures using existing `_decision`, `_view`, `_gate`, and `SignalArbiter` helpers. Required scenarios:

```python
def test_batch_arbitration_keeps_opposite_legs_in_same_pair() -> None:
    actor = DecisionPolicyActor(gate=_gate(dedupe_enabled=False))
    up = _decision(side=Side.UP, order_intent=OrderIntentSpec(OrderIntent.PASSIVE_GTD, pair_id="pair-1"))
    down = _decision(side=Side.DOWN, order_intent=OrderIntentSpec(OrderIntent.PASSIVE_GTD, pair_id="pair-1"))

    assert actor.batch_arbitrate([(up, _view()), (down, _view())]) == [up, down]


def test_invalid_batch_candidate_cannot_suppress_valid_opposite_candidate() -> None:
    actor = _actor_for("accepted")
    invalid = _decision(side=Side.UP, max_entry_price=0.10)
    valid = _decision(side=Side.DOWN, max_entry_price=0.90)
    view = _view_for("accepted")

    assert actor.batch_arbitrate([(invalid, view), (valid, view)]) == [valid]
```

Add a strategy-level test where an injected policy raises from `batch_arbitrate`; assert `submit_order` is never called and runtime progress contains a named degradation phase.

- [ ] **Step 2: Confirm failures**

Run:

```bash
uv run pytest tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_alpha_pre_order_market.py -v
```

Expected: paired legs are removed or invalid candidate participates; arbiter exception currently submits original decisions.

- [ ] **Step 3: Implement prevalidation and atomic pair groups**

Introduce one private method in `DecisionPolicyActor` that obtains a candidate through `_candidate_from_decision`, checks `_skip_reason_for`, and invokes `gate.evaluate` without adding consensus. Return `SignalCandidate | RejectedDecision`.

`batch_arbitrate` must:

```python
# First group by OrderIntentSpec.pair_id / SignalCandidate.pair_id.
# Validate every raw decision before adding its candidate to conflict arbitration.
# Keep an entire pair only when all its members validate; paired candidates do not
# participate in suppress_ambiguous against sibling pair legs.
# Pass only eligible non-paired candidates to self.arbiter.arbitrate(...).
# Return decisions in their original order, never deriving priority from enumerate.
```

Use explicit stable configuration mapping only when one already exists in the policy assembly; otherwise retain the arbiter's deterministic input order after sorting by stable `(strategy, market_id, token_id, side.value)` key. Do not use callback arrival order as a priority source.

- [ ] **Step 4: Make native use fail closed**

Replace the broad fallback with:

```python
try:
    survivors = self._decision_pipeline.try_batch_arbitrate(batch)
except Exception:
    self._note_runtime_progress("arbitration_failed")
    return
```

Do not submit original decisions. Preserve normal single-decision handling unless the policy API is deliberately changed in this task.

- [ ] **Step 5: Verify grouped behavior and existing pipeline**

Run:

```bash
uv run pytest tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_alpha_pre_order_market.py tests/test_nautilus_cross_market.py -v
```

Expected: paired UP/DOWN decisions survive, invalid candidates cannot suppress valid candidates, arbiter failures yield no order, existing decision pipeline remains green.

---

### Task 4: Make event-time conversion strict and replay deterministic

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/strategy/event_projection.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategy/helpers.py`
- Modify: `src/polysignal_lab/nautilus_bridge/market_view_assembler.py:57-88`
- Modify: `src/polysignal_lab/alpha/dump_hedge_core.py`, `low_side_dual_reversion_core.py`, `pre_order_market_core.py`
- Test: `tests/test_nautilus_projections.py`
- Test: `tests/test_nautilus_market_view_assembler.py`
- Test: `tests/test_alpha_dump_hedge.py`, `tests/test_alpha_pre_order_market.py`

**Interfaces:**
- Consumes: positive Nautilus Unix-nanosecond `ts_event: int` or existing timezone-aware `datetime` test doubles.
- Produces: `event_datetime(value: object) -> datetime`; invalid/missing timestamp raises `ValueError`; alpha timing derives from `MarketView.created_at`.

- [ ] **Step 1: Add failing projection tests**

```python
def test_project_order_event_converts_nautilus_nanoseconds_to_utc() -> None:
    event = SimpleNamespace(ts_event=1_788_451_200_123_456_789)
    projected = project_order_event(event, registry=None, strategy_name="alpha", metrics_lookup=lambda _: {})

    assert projected.ts_event == datetime.fromtimestamp(1_788_451_200.1234567, UTC)


def test_project_order_event_rejects_missing_event_time() -> None:
    event = SimpleNamespace(ts_event=0)

    with pytest.raises(ValueError, match="ts_event"):
        project_order_event(event, registry=None, strategy_name="alpha", metrics_lookup=lambda _: {})
```

Add a fixed `MarketView.created_at` test proving Dump Hedge detection and pre-order expiry output do not change when `datetime.now()` is monkeypatched.

- [ ] **Step 2: Confirm the current wall-clock fallback**

Run: `uv run pytest tests/test_nautilus_projections.py tests/test_alpha_dump_hedge.py tests/test_alpha_pre_order_market.py -v`

Expected: integer timestamp is replaced by the current clock or invalid timestamp does not fail.

- [ ] **Step 3: Implement one strict converter**

Use a single helper, located with the event projection boundary:

```python
def event_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("ts_event datetime must be timezone-aware")
        return value.astimezone(UTC)
    if not isinstance(value, int) or value <= 0:
        raise ValueError("ts_event must be a positive Unix nanosecond timestamp")
    return datetime.fromtimestamp(value / 1_000_000_000, UTC)
```

Replace `_datetime_or_now` calls and remove that fallback. Remove unused `_utc_now()` helpers from the three alpha cores after their existing `_now_from(view)` calls are verified as the only logical clock source.

- [ ] **Step 4: Make view construction explicit at replay boundaries**

Keep `MarketViewAssembler.build(..., created_at=...)` for callers that already supply source event time. Audit replay-facing callers and pass their event-derived time. Do not change live-only call sites merely to manufacture timestamps; when source time is unavailable, make the replay test path supply it explicitly.

- [ ] **Step 5: Run deterministic time verification**

Run:

```bash
uv run pytest tests/test_nautilus_projections.py tests/test_nautilus_market_view_assembler.py tests/test_alpha_dump_hedge.py tests/test_alpha_pre_order_market.py -v
```

Expected: Unix-nanos conversion and fixed-view replay tests pass, and no tested logic falls back to ambient clock.

---

### Task 5: Prohibit synchronous crypto-price HTTP on Actor paths

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/market_rotation.py:96-116,264-361`
- Test: `tests/test_nautilus_market_rotation.py`

**Interfaces:**
- Consumes: `Settings.data.polymarket.use_crypto_price_api`.
- Produces: native actor construction rejects `True` with a clear `ValueError`; no `PriceToBeatProvider.get_sync()` call from an Actor callback.

- [ ] **Step 1: Add the failing actor configuration test**

```python
def test_market_rotation_rejects_crypto_price_http_fallback() -> None:
    settings = Settings()
    settings.data.polymarket.use_crypto_price_api = True

    with pytest.raises(ValueError, match="crypto-price API.*Actor"):
        MarketRotationActor(
            settings=settings,
            startup_markets=(),
            market_universe=_Universe([[]]),
            catalog=MarketCatalog(),
            anchor_store=None,
            health=None,
        )
```

Add a test double whose `get_sync` raises `AssertionError`; invoke `_on_refresh_timer` under normal settings and assert it is not called.

- [ ] **Step 2: Confirm it fails**

Run: `uv run pytest tests/test_nautilus_market_rotation.py -v`

Expected: actor accepts the unsafe setting or reaches synchronous provider logic.

- [ ] **Step 3: Fail fast in the Actor constructor**

Before constructing `PriceToBeatProvider`, add:

```python
if settings.data.polymarket.use_crypto_price_api:
    raise ValueError(
        "crypto-price API fallback is unsupported in MarketRotationActor; "
        "publish PriceToBeat through a worker or Nautilus CustomData source"
    )
```

Instantiate the actor-local provider with `use_crypto_price_api=False`. Preserve anchor, metadata, and CustomData behavior.

- [ ] **Step 4: Verify actor path**

Run: `uv run pytest tests/test_nautilus_market_rotation.py tests/test_price_to_beat_provider.py -v`

Expected: actor rejects unsafe configuration; standalone provider tests retain their own non-actor coverage.

---

### Task 6: Close directly related mutability and validation debt

**Files:**
- Modify: `src/polysignal_lab/alpha/vwap_trade_history.py:119-129`
- Modify: `src/polysignal_lab/alpha/vwap_momentum_core.py:512-538` only if required by immutable returns
- Test: `tests/test_vwap_trade_history.py`, `tests/test_alpha_vwap_momentum.py`
- Modify: `src/polysignal_lab/storage/sqlite_store.py:655-657`

**Interfaces:**
- Produces: `trades_for_key() -> tuple[Trade, ...]`; `all_trades() -> dict[str, tuple[Trade, ...]]`; callers cannot mutate internal history through a snapshot.

- [ ] **Step 1: Add the failing snapshot isolation test**

```python
def test_trade_history_snapshots_cannot_mutate_internal_state() -> None:
    history = TradeHistory()
    history.push("market", 0.5, 2.0, 1.0)

    snapshot = history.trades_for_key("market")

    assert isinstance(snapshot, tuple)
    assert history.latest_price("market") == 0.5
```

- [ ] **Step 2: Implement immutable snapshots**

```python
def trades_for_key(self, key: str) -> tuple[Trade, ...]:
    return tuple(self._trades.get(key, ()))


def all_trades(self) -> dict[str, tuple[Trade, ...]]:
    return {key: tuple(trades) for key, trades in self._trades.items()}
```

Adjust only consumers that require an iterable. Remove the trailing blank line at end of `sqlite_store.py` so `git diff --check` is clean.

- [ ] **Step 3: Verify**

Run:

```bash
uv run pytest tests/test_vwap_trade_history.py tests/test_alpha_vwap_momentum.py -v
git diff --check
```

Expected: tests pass and no whitespace errors.

---

### Task 7: Execute full verification and synchronize remediation tracking

**Files:**
- Modify only after evidence is complete: `.omo/plans/nautilus-architecture-remediation.md`
- Modify only if results change: `docs/architecture-remediation-results-2026-07-09.md`

**Interfaces:**
- Consumes: completed task tests and actual command output.
- Produces: accurate plan checkboxes and result document with no claims not supported by current verification.

- [ ] **Step 1: Run focused aggregate tests**

```bash
uv run pytest \
  tests/test_docker_entrypoint.py \
  tests/test_alpha_types.py \
  tests/test_nautilus_dependency_boundary.py \
  tests/test_nautilus_decision_policy.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_cross_market.py \
  tests/test_nautilus_projections.py \
  tests/test_nautilus_market_view_assembler.py \
  tests/test_alpha_dump_hedge.py \
  tests/test_alpha_pre_order_market.py \
  tests/test_nautilus_market_rotation.py \
  tests/test_vwap_trade_history.py \
  tests/test_alpha_vwap_momentum.py -v
```

Expected: PASS.

- [ ] **Step 2: Run default Python 3.11 boundary verification**

```bash
uv run --python 3.11 python -c 'import polysignal_lab; import polysignal_lab.alpha'
uv run --python 3.11 pytest tests/test_nautilus_dependency_boundary.py tests/test_alpha_types.py -v
```

Expected: PASS without Nautilus installed.

- [ ] **Step 3: Run optional Nautilus bridge verification**

```bash
uv sync --python 3.12 --extra nautilus
uv run --python 3.12 pytest \
  tests/test_nautilus_full_paper_runtime_smoke.py \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_dependency_boundary.py -v
```

Expected: PASS. If the environment cannot install the extra, capture the exact non-code limitation in the results document and do not mark bridge verification complete.

- [ ] **Step 4: Run repository gates**

```bash
uv run pytest -q
uv run ruff check src/polysignal_lab --select F401,F841
uv run polysignal-safety-scan .
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Update tracking only with verified evidence**

Mark implementation items complete in `.omo/plans/nautilus-architecture-remediation.md` only after all corresponding acceptance commands pass. Update result counts, bridge version, and unresolved environment limitations in `docs/architecture-remediation-results-2026-07-09.md` only from actual output. Do not commit or push without a separate user request.

---

## Self-Review

- **Spec coverage:** Tasks 1–5 address every P0/P1 blocker: Docker default, pair-safe arbitration, eligibility and stable handling, fail-closed errors, Python 3.11 alpha boundary, strict event time, and actor HTTP. Task 6 handles only directly related P2 mutability/whitespace. Task 7 performs all required acceptance checks and reconciles stale tracking.
- **Placeholder scan:** No TBD/TODO markers or generic test instructions remain; every task has commands and concrete expected outcomes.
- **Type consistency:** `batch_arbitrate` continues consuming `list[tuple[AlphaDecision, MarketView]]`; pair identity comes from existing order intent/candidate fields; `event_datetime` produces UTC `datetime`; trade snapshots are tuples throughout.
