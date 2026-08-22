from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Any, Protocol, cast

from polysignal_lab.alpha.types import CachedPositionView, TradingStateView
from polysignal_lab.domain.enums import Side
from polysignal_lab.data.gamma_resolution import (
    ResolvedMarketEvidence,
    query_resolved_markets_by_conditions,
)
from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    get_polymarket_condition_id,
    get_polymarket_token_id,
)
from polysignal_lab.nautilus_runtime.cache_trading_state import trading_state_from_cache
from polysignal_lab.nautilus_runtime.custom_data_state import event_datetime
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.reporting.exit_result import report_result_from_resolution
from polysignal_lab.utils import utc_iso

_pyo3 = cast(Any, load_nautilus_module("nautilus_trader.core.nautilus_pyo3"))
PositionId = _pyo3.PositionId
InstrumentId = _pyo3.InstrumentId
TimeInForce = _pyo3.TimeInForce

_RESOLUTION_EVIDENCE_TTL_SEC = 30.0
_resolution_evidence_cache: dict[str, tuple[float, ResolvedMarketEvidence]] = {}


class _ResolutionStrategy(Protocol):
    cache: object | None
    registry: MarketCatalog | None
    strategy_name: str
    observability: object | None
    _execution_mode: str
    _settled_position_keys: set[tuple[str, str]]

    id: object | None
    strategy_id: object | None

    def _note_runtime_progress(self, phase: str) -> None: ...

    def close_position(
        self,
        position: object,
        *,
        client_id: object | None = None,
        tags: Sequence[str] | None = None,
        time_in_force: object | None = None,
        reduce_only: bool | None = None,
        quote_quantity: bool | None = None,
        params: Mapping[str, object] | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    strategy: str
    position_id: str
    report_position_id: str
    instrument_id: str
    condition_id: str
    token_id: str
    side: str
    market_id: str
    market_slug: str
    asset: str
    timeframe: str
    entry_price: float
    quantity: float
    stake_usdc: float | None
    opened_at: str


def handle_instrument_close(strategy: _ResolutionStrategy, close: object) -> None:
    """Settle open positions from an official Nautilus ``InstrumentClose`` event.

    This is the optional fast path. The persistent reconciliation below can
    still settle the same position independently, so both share one builder
    and one deterministic report result id.
    """
    if getattr(strategy, "_execution_mode", "live") == "backtest":
        return
    registry = strategy.registry
    if registry is None:
        return
    outcome_value = _zero_or_one(getattr(close, "close_price", None))
    if outcome_value is None:
        strategy._note_runtime_progress("resolution_close_price_unsupported")
        return
    identity = _pair_token_for_instrument(
        registry,
        _identifier_text(getattr(close, "instrument_id", None)),
    )
    if identity is None:
        strategy._note_runtime_progress("resolution_close_identity_missing")
        return
    pair, token = identity
    trading = _trading_for_condition(strategy, registry, pair.condition_id)
    if trading is None:
        strategy._note_runtime_progress("resolution_trading_state_failed")
        return
    matches = _close_position_matches(trading, close, token.side)
    if not matches:
        strategy._note_runtime_progress("resolution_close_position_missing")
        return
    _settle_positions(
        strategy,
        trading=trading,
        pair=pair,
        token=token,
        positions=matches,
        outcome_value=outcome_value,
        closed_at=_close_timestamp(close),
    )


def resolve_open_positions(
    strategy: _ResolutionStrategy,
    *,
    now: datetime,
    fetch_evidence: Any | None = None,
) -> None:
    """Reconcile persistent OPEN positions against strict Gamma resolution.

    The registry and the Cache only contribute current positions; rows treated
    as authoritative are ``report_positions.status=OPEN``. If the historical
    condition is absent from the active registry, the persistent row still
    parses through the official Polymarket instrument helpers and settles.
    """
    if getattr(strategy, "_execution_mode", "live") == "backtest":
        return
    candidates = _collect_open_candidates(strategy, strategy.registry)
    if not candidates:
        return
    condition_ids = tuple(dict.fromkeys(candidate.condition_id for candidate in candidates))
    fetcher = fetch_evidence or _cached_fetch_condition_evidence
    try:
        evidence_by_condition = fetcher(condition_ids, now=now)
    except Exception:
        strategy._note_runtime_progress("resolution_evidence_fetch_failed")
        return
    if not evidence_by_condition:
        strategy._note_runtime_progress("resolution_no_resolved_evidence")
        return
    for candidate in candidates:
        evidence = evidence_by_condition.get(candidate.condition_id)
        if evidence is None:
            continue
        outcome = evidence.outcome_for_token(candidate.token_id)
        if outcome is None:
            strategy._note_runtime_progress("resolution_token_missing")
            continue
        _settle_candidate(strategy, candidate, outcome_value=outcome, now=now)


def _cached_fetch_condition_evidence(
    condition_ids: Sequence[str],
    *,
    now: datetime,
) -> dict[str, ResolvedMarketEvidence]:
    """Fetch strict evidence once per condition per short TTL."""
    global _resolution_evidence_cache
    now_ts = _datetime_timestamp(now)
    ids = tuple(dict.fromkeys(str(value).strip() for value in condition_ids if value))
    missing = tuple(
        condition_id
        for condition_id in ids
        if condition_id not in _resolution_evidence_cache
        or now_ts - _resolution_evidence_cache[condition_id][0] >= _RESOLUTION_EVIDENCE_TTL_SEC
    )
    if missing:
        try:
            from polysignal_lab.config import load_settings

            settings = load_settings()
            fetched = query_resolved_markets_by_conditions(
                missing,
                gamma_base_url=settings.data.polymarket.gamma_base_url,
            )
        except Exception:
            fetched = {}
        for condition_id, evidence in fetched.items():
            _resolution_evidence_cache[condition_id] = (now_ts, evidence)
    return {
        condition_id: _resolution_evidence_cache[condition_id][1]
        for condition_id in ids
        if condition_id in _resolution_evidence_cache
    }


def _datetime_timestamp(value: datetime) -> float:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.timestamp()


def _collect_open_candidates(
    strategy: _ResolutionStrategy,
    registry: MarketCatalog | None,
) -> tuple[ResolutionCandidate, ...]:
    by_key: dict[tuple[str, str], ResolutionCandidate] = {}
    if registry is not None:
        try:
            trading = trading_state_from_cache(
                strategy.cache,
                strategy_id=getattr(strategy, "id", None)
                or getattr(strategy, "strategy_id", None),
                registry=registry,
            )
        except (TypeError, ValueError, RuntimeError):
            trading = TradingStateView()
        for position in trading.positions:
            candidate = _candidate_from_cache_position(position, registry)
            if candidate is not None:
                by_key[(candidate.strategy, candidate.report_position_id)] = candidate
    for row in _persistent_open_position_rows(strategy):
        candidate = _candidate_from_report_position(
            row,
            strategy.strategy_name,
            registry=registry,
        )
        if candidate is not None:
            key = (candidate.strategy, candidate.report_position_id)
            by_key.setdefault(key, candidate)
    return tuple(by_key.values())


def _trading_for_condition(
    strategy: _ResolutionStrategy,
    registry: MarketCatalog,
    condition_id: str,
) -> TradingStateView | None:
    try:
        return trading_state_from_cache(
            strategy.cache,
            strategy_id=getattr(strategy, "id", None)
            or getattr(strategy, "strategy_id", None),
            registry=registry,
            condition_id=condition_id,
        )
    except (TypeError, ValueError, RuntimeError):
        return None


def _close_position_matches(
    trading: TradingStateView,
    close: object,
    side: Side,
) -> tuple[CachedPositionView, ...]:
    instrument_id = str(getattr(close, "instrument_id", ""))
    return tuple(
        position
        for position in trading.positions
        if position.instrument_id == instrument_id and position.side is side
    )


def _settle_positions(
    strategy: _ResolutionStrategy,
    *,
    trading: TradingStateView,
    pair: MarketPairMeta,
    token: InstrumentTokenMeta,
    positions: Sequence[CachedPositionView],
    outcome_value: float,
    closed_at: str,
) -> None:
    for position in positions:
        _settle_cache_position(
            strategy,
            trading=trading,
            pair=pair,
            token=token,
            position=position,
            outcome_value=outcome_value,
            closed_at=closed_at,
        )


def _settle_cache_position(
    strategy: _ResolutionStrategy,
    *,
    trading: TradingStateView,
    pair: MarketPairMeta,
    token: InstrumentTokenMeta,
    position: CachedPositionView,
    outcome_value: float,
    closed_at: str,
) -> None:
    position_id = str(position.position_id)
    settlement_key = (str(position.strategy), position_id)
    if settlement_key in strategy._settled_position_keys:
        strategy._note_runtime_progress("resolution_result_duplicate")
        return
    if trading.has_exit_order(position_id):
        strategy._note_runtime_progress("resolution_exit_order_pending")
        return

    raw_position = _cache_position(strategy, position_id)
    metrics = _cache_position_metrics(position, pair, token, closed_at)
    result = report_result_from_resolution(
        metrics,
        outcome_value=outcome_value,
        strategy_name=strategy.strategy_name,
        closed_at=closed_at,
        native_close_requested=False,
    )
    if result is None:
        strategy._note_runtime_progress("resolution_result_quarantined")
        return
    if not _record_resolution_result(strategy, result):
        return

    strategy._settled_position_keys.add(settlement_key)
    _request_native_close(strategy, raw_position, position_id)


def _settle_candidate(
    strategy: _ResolutionStrategy,
    candidate: ResolutionCandidate,
    *,
    outcome_value: float,
    now: datetime,
) -> None:
    settlement_key = (candidate.strategy, candidate.report_position_id)
    if settlement_key in strategy._settled_position_keys:
        strategy._note_runtime_progress("resolution_result_duplicate")
        return

    raw_position = _cache_position(strategy, candidate.position_id)
    metrics = _candidate_metrics(candidate, now=now)
    result = report_result_from_resolution(
        metrics,
        outcome_value=outcome_value,
        strategy_name=strategy.strategy_name,
        closed_at=utc_iso(now),
        native_close_requested=False,
    )
    if result is None:
        strategy._note_runtime_progress("resolution_result_quarantined")
        return
    if not _record_resolution_result(strategy, result):
        return

    strategy._settled_position_keys.add(settlement_key)
    _request_native_close(strategy, raw_position, candidate.position_id)


def _candidate_from_cache_position(
    position: CachedPositionView,
    registry: MarketCatalog,
) -> ResolutionCandidate | None:
    pair = registry.by_condition(position.condition_id)
    if pair is None:
        return None
    token = pair.up if position.side is Side.UP else pair.down
    return _make_candidate(
        strategy=str(position.strategy),
        position_id=str(position.position_id),
        report_position_id=str(position.position_id),
        instrument_id=str(position.instrument_id),
        condition_id=str(position.condition_id),
        token_id=str(token.token_id),
        side=position.side.value,
        market_id=str(position.market_id) or pair.market_id,
        market_slug=pair.market_slug,
        asset=pair.asset,
        timeframe=pair.timeframe,
        entry_price=float(position.avg_entry_price),
        quantity=float(position.quantity),
        stake_usdc=None,
        opened_at=(
            position.opened_at.isoformat()
            if position.opened_at is not None
            else ""
        ),
    )


def _candidate_from_report_position(
    row: Mapping[str, object],
    strategy_name: str,
    *,
    registry: MarketCatalog | None = None,
) -> ResolutionCandidate | None:
    identity = _report_position_identity(row)
    if identity is None:
        return None
    report_position_id, position_id, instrument_id, condition_id, token_id = identity
    pair = registry.by_condition(condition_id) if registry is not None else None

    side = _row_text(row, "side").upper()
    if side not in {"UP", "DOWN"} and pair is not None:
        if token_id == str(pair.up.token_id):
            side = Side.UP.value
        elif token_id == str(pair.down.token_id):
            side = Side.DOWN.value
    if side not in {"UP", "DOWN"}:
        return None

    pricing = _report_position_pricing(row)
    if pricing is None:
        return None
    entry_price, shares, stake = pricing

    metadata = _report_position_metadata(row, strategy_name, pair=pair)
    if metadata is None:
        return None
    strategy, market_id, market_slug, asset, timeframe, opened_at = metadata
    return _make_candidate(
        strategy=strategy,
        position_id=position_id,
        report_position_id=report_position_id,
        instrument_id=instrument_id,
        condition_id=condition_id,
        token_id=token_id,
        side=side,
        market_id=market_id,
        market_slug=market_slug,
        asset=asset,
        timeframe=timeframe,
        entry_price=entry_price,
        quantity=shares,
        stake_usdc=stake,
        opened_at=opened_at,
    )


def _report_position_identity(
    row: Mapping[str, object],
) -> tuple[str, str, str, str, str] | None:
    report_position_id = _row_text(row, "report_position_id", "position_id")
    position_id = _row_text(row, "position_id") or report_position_id
    instrument_id = _row_text(row, "instrument_id")
    parsed = _polymarket_condition_token(instrument_id)
    if parsed is None:
        return None
    condition_id, token_id = parsed
    if not (report_position_id and position_id and instrument_id):
        return None
    return report_position_id, position_id, instrument_id, condition_id, token_id


def _report_position_pricing(
    row: Mapping[str, object],
) -> tuple[float, float, float] | None:
    entry_price = _positive_float(
        _row_value(row, "entry_price", "avg_entry_price", "price")
    )
    shares = _positive_float(
        _row_value(row, "shares", "quantity", "position_quantity", "signed_qty")
    )
    if entry_price is None or shares is None:
        return None
    stake = _positive_float(_row_value(row, "stake_usdc"))
    if stake is None:
        stake = entry_price * shares
    return entry_price, shares, stake


def _report_position_metadata(
    row: Mapping[str, object],
    strategy_name: str,
    *,
    pair: MarketPairMeta | None = None,
) -> tuple[str, str, str, str, str, str] | None:
    strategy = _row_text(row, "strategy", "owning_strategy") or strategy_name
    market_id = _row_text(row, "market_id") or (
        pair.market_id if pair is not None else ""
    )
    market_slug = _row_text(row, "market_slug") or (
        pair.market_slug if pair is not None else ""
    )
    asset = _row_text(row, "asset").upper() or (
        pair.asset if pair is not None else ""
    )
    timeframe = _row_text(row, "timeframe").lower() or (
        pair.timeframe if pair is not None else ""
    )
    if not (strategy and market_id and market_slug and asset and timeframe):
        return None
    opened_at = _row_text(row, "opened_at", "ts", "created_at")
    return strategy, market_id, market_slug, asset, timeframe, opened_at


def _make_candidate(
    *,
    strategy: str,
    position_id: str,
    report_position_id: str,
    instrument_id: str,
    condition_id: str,
    token_id: str,
    side: str,
    market_id: str,
    market_slug: str,
    asset: str,
    timeframe: str,
    entry_price: float,
    quantity: float,
    stake_usdc: float | None,
    opened_at: str,
) -> ResolutionCandidate | None:
    if not (
        strategy
        and position_id
        and report_position_id
        and condition_id
        and token_id
        and market_id
        and market_slug
        and asset
        and timeframe
    ):
        return None
    return ResolutionCandidate(
        strategy=strategy,
        position_id=position_id,
        report_position_id=report_position_id,
        instrument_id=instrument_id,
        condition_id=condition_id,
        token_id=token_id,
        side=side,
        market_id=market_id,
        market_slug=market_slug,
        asset=asset,
        timeframe=timeframe,
        entry_price=entry_price,
        quantity=quantity,
        stake_usdc=stake_usdc,
        opened_at=opened_at,
    )


def _cache_position_metrics(
    position: CachedPositionView,
    pair: MarketPairMeta,
    token: InstrumentTokenMeta,
    closed_at: str,
) -> dict[str, object]:
    position_id = str(position.position_id)
    stake = float(position.avg_entry_price) * float(position.quantity)
    return metrics_for(
        position_id=position_id,
        report_position_id=position_id,
        strategy=str(position.strategy),
        side=token.side.value,
        pair=pair,
        entry_price=float(position.avg_entry_price),
        quantity=float(position.quantity),
        stake_usdc=stake,
        opened_at=(
            position.opened_at.isoformat()
            if position.opened_at is not None
            else closed_at
        ),
    )


def _candidate_metrics(
    candidate: ResolutionCandidate,
    *,
    now: datetime,
) -> dict[str, object]:
    pair = _pair_from_candidate(candidate)
    return metrics_for(
        position_id=candidate.position_id,
        report_position_id=candidate.report_position_id,
        strategy=candidate.strategy,
        side=candidate.side,
        pair=pair,
        entry_price=candidate.entry_price,
        quantity=candidate.quantity,
        stake_usdc=candidate.stake_usdc,
        opened_at=candidate.opened_at or utc_iso(now),
    )


def metrics_for(
    *,
    position_id: str,
    report_position_id: str,
    strategy: str,
    side: str,
    pair: MarketPairMeta | None,
    entry_price: float,
    quantity: float,
    stake_usdc: float | None,
    opened_at: str,
) -> dict[str, object]:
    market_id = pair.market_id if pair is not None else ""
    market_slug = pair.market_slug if pair is not None else ""
    asset = pair.asset if pair is not None else ""
    timeframe = pair.timeframe if pair is not None else ""
    return {
        "position_id": position_id,
        "report_position_id": report_position_id,
        "signal_id": f"resolution:{report_position_id}",
        "strategy": strategy,
        "owning_strategy": strategy,
        "asset": asset,
        "timeframe": timeframe,
        "market_id": market_id,
        "market_slug": market_slug,
        "side": side,
        "entry_price": entry_price,
        "position_quantity": quantity,
        "quantity": quantity,
        "stake_usdc": (
            stake_usdc if stake_usdc is not None else entry_price * quantity
        ),
        "opened_at": opened_at,
    }


def _pair_from_candidate(candidate: ResolutionCandidate) -> MarketPairMeta | None:
    try:
        return MarketPairMeta(
            market_id=candidate.market_id,
            market_slug=candidate.market_slug,
            condition_id=candidate.condition_id,
            asset=candidate.asset,
            timeframe=candidate.timeframe,
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta(token_id="", side=Side.UP),
            down=InstrumentTokenMeta(token_id="", side=Side.DOWN),
        )
    except (TypeError, ValueError):
        return None


def _persistent_open_position_rows(
    strategy: _ResolutionStrategy,
) -> tuple[Mapping[str, object], ...]:
    observability = getattr(strategy, "observability", None)
    if observability is None:
        return ()
    query = getattr(observability, "query_report_open_positions", None)
    if not callable(query):
        return ()
    try:
        rows = query()
    except Exception:
        strategy._note_runtime_progress("resolution_report_position_query_failed")
        return ()
    if rows is None:
        return ()
    try:
        return tuple(
            cast(Mapping[str, object], row)
            for row in cast(Iterable[Mapping[str, object]], rows)
            if isinstance(row, Mapping)
        )
    except TypeError:
        return ()


def _should_request_native_close(
    strategy: _ResolutionStrategy,
    raw_position: object | None,
) -> bool:
    return (
        getattr(strategy, "_execution_mode", "") == "sandbox"
        and raw_position is not None
        and not bool(getattr(raw_position, "is_closed", False))
    )


def _request_native_close(
    strategy: _ResolutionStrategy,
    raw_position: object | None,
    position_id: str,
) -> None:
    if not _should_request_native_close(strategy, raw_position):
        return
    tags = (
        "resolution_settlement_close=true",
        "exit_reason=RESOLUTION",
        f"position_id={position_id}",
    )
    try:
        strategy.close_position(
            raw_position,
            time_in_force=TimeInForce.IOC,
            reduce_only=True,
            tags=tags,
        )
        strategy._note_runtime_progress("resolution_native_close_requested")
    except (TypeError, ValueError, RuntimeError):
        strategy._note_runtime_progress("resolution_native_close_failed")


def _record_resolution_result(
    strategy: _ResolutionStrategy,
    result: Mapping[str, object],
) -> bool:
    observability = getattr(strategy, "observability", None)
    if observability is None:
        return False
    recorder = getattr(observability, "record_event", None)
    if not callable(recorder):
        return False
    try:
        created = recorder("settlements", result)
    except Exception:
        strategy._note_runtime_progress("resolution_result_failed")
        return False
    if created is False:
        strategy._note_runtime_progress("resolution_result_duplicate")
        return True
    strategy._note_runtime_progress("resolution_result")
    return True


def _cache_position(strategy: _ResolutionStrategy, position_id: str) -> object | None:
    cache = strategy.cache
    if cache is None:
        return None
    try:
        cache_position_id = PositionId.from_str(position_id)
    except ValueError:
        return None
    getter = getattr(cache, "position", None)
    if not callable(getter):
        return None
    try:
        return getter(cache_position_id)
    except (LookupError, TypeError, ValueError, AttributeError):
        return None


def _pair_token_for_instrument(
    registry: MarketCatalog,
    instrument_key: str | None,
) -> tuple[MarketPairMeta, InstrumentTokenMeta] | None:
    if instrument_key is None:
        return None
    for condition_id in registry.condition_ids():
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token in (pair.up, pair.down):
            instrument_id = registry.instrument_id_for_token(token.token_id)
            if instrument_id is not None and str(instrument_id) == instrument_key:
                return pair, token
    return None


def _polymarket_condition_token(
    instrument_id: str,
) -> tuple[str, str] | None:
    if not instrument_id:
        return None
    try:
        parsed = InstrumentId.from_str(instrument_id)
    except (TypeError, ValueError):
        return None
    venue = getattr(getattr(parsed, "venue", None), "value", None)
    if venue is None:
        venue = str(getattr(parsed, "venue", None))
    if str(venue).strip().upper() != "POLYMARKET":
        return None
    try:
        return (
            str(get_polymarket_condition_id(parsed)),
            str(get_polymarket_token_id(parsed)),
        )
    except (TypeError, ValueError):
        return None


def _zero_or_one(value: object) -> float | None:
    number = _number(value)
    return number if number in (0.0, 1.0) else None


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    candidate = value
    for name in ("as_double", "as_decimal"):
        converter = getattr(value, name, None)
        if callable(converter):
            candidate = converter()
            break
    try:
        number = float(str(candidate))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _identifier_text(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", None)
    text = str(raw if raw is not None else value)
    return text or None


def _close_timestamp(close: object) -> str:
    try:
        return event_datetime(getattr(close, "ts_event", None)).isoformat()
    except (TypeError, ValueError):
        return utc_iso()


def _row_text(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _row_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None
