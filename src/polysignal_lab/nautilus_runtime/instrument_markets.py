from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast, final

from pydantic import JsonValue

from polysignal_lab.config import MarketConfig
from polysignal_lab.data.market_discovery_helpers import match_crypto_updown
from polysignal_lab.data.provider.gamma_market import market_status_from_gamma
from polysignal_lab.domain.enums import MarketStatus
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_instrument_id,
)

polymarket_symbol = load_nautilus_module(
    "nautilus_trader.adapters.polymarket.common.symbol"
)
_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
InstrumentId = _pyo3.InstrumentId

_get_condition_id = cast(
    Callable[[InstrumentId], str],
    polymarket_symbol.get_polymarket_condition_id,
)
_get_token_id = cast(
    Callable[[InstrumentId], str],
    polymarket_symbol.get_polymarket_token_id,
)


@final
class PolymarketInstrumentMarketBuilder:
    """Build complete binary Market projections from Nautilus Instruments."""

    def __init__(self, market_config: MarketConfig) -> None:
        self._market_config = market_config
        self._instruments: dict[str, dict[str, object]] = {}
        self._terminal_condition_ids: set[str] = set()

    def restore_terminal_conditions(self, condition_ids: object) -> None:
        if not isinstance(condition_ids, list):
            return
        for condition_id in cast(list[object], condition_ids):
            text = str(condition_id)
            if text:
                self._terminal_condition_ids.add(text)

    def terminal_condition_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._terminal_condition_ids))

    def record_terminal_condition(self, instrument: object) -> str | None:
        parsed = _instrument_payload(instrument)
        if parsed is None:
            return None
        condition_id, _, _, payload = parsed
        if not self._matches_market(payload) or not _is_terminal_payload(payload):
            return None
        self._terminal_condition_ids.add(condition_id)
        return condition_id

    def add(self, instrument: object) -> Market | None:
        parsed = _instrument_payload(instrument)
        if parsed is None:
            return None
        condition_id, token_id, _, payload = parsed
        matched = self._matched_market(payload)
        if matched is None:
            return None
        if _is_terminal_payload(payload):
            self._terminal_condition_ids.add(condition_id)
        by_token = self._instruments.setdefault(condition_id, {})
        by_token[token_id] = instrument
        if len(by_token) != 2:
            return None
        asset, timeframe = matched
        ordered = tuple(by_token.values())
        payload.update(
            {
                "id": payload.get("id") or condition_id,
                "conditionId": condition_id,
                "clobTokenIds": [
                    _get_token_id(_instrument_id(item)) for item in ordered
                ],
                "outcomes": [str(getattr(item, "outcome", "")) for item in ordered],
            }
        )
        market = Market.from_gamma(
            cast(dict[str, JsonValue], payload), asset, timeframe
        )
        if condition_id in self._terminal_condition_ids and market.is_active:
            return None
        return market

    def _matches_market(self, payload: dict[str, object]) -> bool:
        return self._matched_market(payload) is not None

    def _matched_market(self, payload: dict[str, object]) -> tuple[str, str] | None:
        return match_crypto_updown(
            cast(dict[str, JsonValue], payload),
            assets=list(self._market_config.assets),
            timeframes=list(self._market_config.timeframes),
        )


def _instrument_payload(
    instrument: object,
) -> tuple[str, str, str, dict[str, object]] | None:
    instrument_id = _instrument_id(instrument)
    condition_id = _get_condition_id(instrument_id)
    token_id = _get_token_id(instrument_id)
    outcome = str(getattr(instrument, "outcome", "") or "")
    info = getattr(instrument, "info", None)
    if not outcome or not isinstance(info, Mapping):
        return None
    typed_info = cast(Mapping[object, object], info)
    original = typed_info.get("_gamma_original")
    if isinstance(original, Mapping):
        # Test/fixture path that embeds a full Gamma market payload.
        typed_original = cast(Mapping[object, object], original)
        payload = {_text_value(key): value for key, value in typed_original.items()}
    else:
        # Official Nautilus Polymarket BinaryOption path (Rust/pyO3 v2 adapter).
        # Info keys match crates/adapters/polymarket/src/http/parse.rs build_info_json;
        # lifecycle lives on BinaryOption activation_ns/expiration_ns, not info.
        payload = _payload_from_nautilus_instrument(instrument, typed_info)
    return condition_id, token_id, outcome, payload


def _is_terminal_payload(payload: dict[str, object]) -> bool:
    return market_status_from_gamma(cast(dict[str, JsonValue], payload)) in {
        MarketStatus.CLOSED,
        MarketStatus.RESOLVED,
        MarketStatus.CANCELLED,
    }


def _instrument_id(instrument: object) -> InstrumentId:
    value = cast(object, getattr(instrument, "id", None))
    if value is None:
        raise ValueError("Nautilus Instrument.id is required")
    return cast(InstrumentId, _nautilus_instrument_id(value))


def _text_value(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def _payload_from_nautilus_instrument(
    instrument: object,
    info: Mapping[object, object],
) -> dict[str, object]:
    """Map official Nautilus BinaryOption → Gamma-shaped Market payload.

    Official Rust adapter instrument.info contains only:
    token_id, condition_id, market_id, question_id, market_slug, neg_risk,
    fee_schedule, game_id. It does not set active/closed/end_date_iso.

    The adapter only publishes non-expired instruments via cache_instrument_if_active,
    so a delivered instrument without explicit closed flags is treated as active.
    Expiration comes from BinaryOption.expiration_ns (official instrument model).
    """
    slug = str(info.get("market_slug") or "")
    condition_id = info.get("condition_id")
    market_id = info.get("market_id") or condition_id
    question = info.get("question") or getattr(instrument, "description", None)
    end_text = _datetime_text(info.get("end_date_iso")) or _ns_to_datetime_text(
        getattr(instrument, "expiration_ns", None)
    )
    start_text = _datetime_text(info.get("game_start_time")) or _ns_to_datetime_text(
        getattr(instrument, "activation_ns", None)
    )
    has_status_flags = any(key in info for key in ("active", "closed", "archived"))
    if has_status_flags:
        active = bool(info.get("active", False))
        closed = bool(info.get("closed", False))
        archived = bool(info.get("archived", False))
    else:
        # Live NT instruments are non-expired when published; default open.
        active = True
        closed = False
        archived = False
    return {
        "id": market_id,
        "conditionId": condition_id,
        "questionID": info.get("question_id"),
        "question": question,
        "slug": slug,
        "eventSlug": slug,
        "eventStartTime": start_text,
        "endDate": end_text,
        "active": active,
        "closed": closed,
        "archived": archived,
    }


def _datetime_text(value: object) -> str | None:
    if isinstance(value, datetime):
        current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return current.astimezone(UTC).isoformat()
    if value in (None, ""):
        return None
    return str(value)


def _ns_to_datetime_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        nanos = int(value)  # pyright: ignore[reportArgumentType]
    except (TypeError, ValueError):
        return None
    if nanos <= 0:
        return None
    return datetime.fromtimestamp(nanos / 1_000_000_000, tz=UTC).isoformat()
