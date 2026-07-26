from __future__ import annotations

from collections.abc import Callable, Sequence

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _identifier_text,
    _nautilus_instrument_id,
)


def catalog_instrument_id_resolver(
    registry: object,
) -> Callable[[str], object]:
    """Resolve token_id → instrument id via MarketCatalog (NT get_polymarket_instrument_id)."""

    def resolve(token_id: str) -> object:
        getter = getattr(registry, "instrument_id_for_token", None)
        if not callable(getter):
            raise RuntimeError("registry must implement instrument_id_for_token")
        instrument_id = getter(token_id)
        if instrument_id is None:
            raise ValueError(f"unknown Polymarket token_id {token_id!r}")
        return instrument_id

    return resolve


def _market_id_for_condition(registry: MarketCatalog, condition_id: str) -> str | None:
    pair = registry.by_condition(condition_id)
    return None if pair is None else pair.market_id


def _token_id_from_catalog_instrument(
    registry: MarketCatalog,
    condition_id: str,
    instrument_id: str,
) -> str | None:
    pair = registry.by_condition(condition_id)
    if pair is None:
        return None
    for token_id in (pair.up.token_id, pair.down.token_id):
        if registry.instrument_id_for_token(token_id) == instrument_id:
            return token_id
    return None


def _condition_id_from_catalog_instrument(
    registry: MarketCatalog,
    condition_ids: Sequence[str],
    instrument_id: str,
) -> str | None:
    for condition_id in condition_ids:
        if (
            _token_id_from_catalog_instrument(registry, condition_id, instrument_id)
            is not None
        ):
            return condition_id
    return None


def _event_side(
    registry: MarketCatalog | None,
    instrument_id: str | None,
    token_id: str | None,
    value: object,
) -> Side:
    if isinstance(value, Side):
        return value
    text = _identifier_text(value)
    if text in {Side.UP.value, Side.DOWN.value}:
        return Side(text)
    if registry is not None:
        resolved_token_id = token_id
        if resolved_token_id is None and instrument_id is not None:
            condition_id = _condition_id_from_catalog_instrument(
                registry, registry.condition_ids(), instrument_id
            )
            if condition_id is not None:
                resolved_token_id = _token_id_from_catalog_instrument(
                    registry, condition_id, instrument_id
                )
        if resolved_token_id is not None:
            meta = registry.token_meta(resolved_token_id)
            if meta is not None:
                return meta.side
    raise ValueError("unresolved order/fill side; refusing Side.UP fabrication")


def _instrument_ids(
    registry: MarketCatalog,
    condition_ids: Sequence[str],
) -> tuple[object, ...]:
    instrument_ids: list[object] = []
    for condition_id in condition_ids:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token_id in (pair.up.token_id, pair.down.token_id):
            instrument_id = registry.instrument_id_for_token(token_id)
            if instrument_id is not None:
                instrument_ids.append(_nautilus_instrument_id(instrument_id))
    return tuple(instrument_ids)


def _asset_conditions(
    registry: MarketCatalog | None,
    condition_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    if registry is None:
        return {}
    grouped: dict[str, list[str]] = {}
    for condition_id in condition_ids:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        grouped.setdefault(pair.asset.upper(), []).append(condition_id)
    return {asset: tuple(ids) for asset, ids in grouped.items()}
