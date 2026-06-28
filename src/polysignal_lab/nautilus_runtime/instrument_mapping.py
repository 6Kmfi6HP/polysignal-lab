from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_registry import InstrumentTokenMeta, MarketPairMeta

DEFAULT_VENUE = "POLYSIGNAL_PM_PAPER"
DEFAULT_TICK_SIZE = 0.001
DEFAULT_SIZE_INCREMENT = 0.000001
DEFAULT_MIN_ORDER_SIZE = 5.0


@dataclass(frozen=True, slots=True)
class NautilusInstrumentMeta:
    token_id: str
    instrument_id: str
    condition_id: str
    side: Side
    tick_size: float
    size_increment: float
    market_slug: str


def instrument_id_for_token(token_id: str, venue: str = DEFAULT_VENUE) -> str:
    stripped = str(token_id).strip()
    if not stripped:
        raise ValueError("token_id must not be empty")
    venue_id = str(venue).strip()
    if not venue_id:
        raise ValueError("venue must not be empty")
    return f"{stripped}.{venue_id}"


def polymarket_instrument_id(condition_id: str, token_id: str) -> str:
    condition = str(condition_id).strip()
    token = str(token_id).strip()
    if not condition:
        raise ValueError("condition_id must not be empty")
    if not token:
        raise ValueError("token_id must not be empty")
    try:
        helper = getattr(
            import_module("nautilus_trader.adapters.polymarket"),
            "get_polymarket_instrument_id",
        )
    except (ModuleNotFoundError, AttributeError):
        return f"{condition}-{token}.POLYMARKET"
    return str(helper(condition, token))


def _positive(value: float, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _unix_ns(value: datetime | None) -> int:
    if value is None:
        return 0
    dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    delta = dt.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def build_binary_option(
    pair: MarketPairMeta,
    token: InstrumentTokenMeta,
    *,
    tick_size: float | None,
    min_order_size: float | None,
    ts_init_ns: int,
) -> object:
    USDC = getattr(import_module("nautilus_trader.model.currencies"), "USDC")
    AssetClass = getattr(import_module("nautilus_trader.model.enums"), "AssetClass")
    identifiers = import_module("nautilus_trader.model.identifiers")
    InstrumentId = getattr(identifiers, "InstrumentId")
    Symbol = getattr(identifiers, "Symbol")
    Venue = getattr(identifiers, "Venue")
    BinaryOption = getattr(import_module("nautilus_trader.model.instruments"), "BinaryOption")
    objects = import_module("nautilus_trader.model.objects")
    Price = getattr(objects, "Price")
    Quantity = getattr(objects, "Quantity")

    tick = _positive(DEFAULT_TICK_SIZE if tick_size is None else tick_size, "tick_size")
    size_increment = _positive(DEFAULT_SIZE_INCREMENT, "size_increment")
    minimum = _positive(DEFAULT_MIN_ORDER_SIZE if min_order_size is None else min_order_size, "min_order_size")
    price_increment = Price.from_str(f"{tick:g}")
    quantity_increment = Quantity.from_str(f"{size_increment:g}")
    instrument_text = str(token.instrument_id or token.token_id).strip()
    if "." in instrument_text:
        symbol_text, venue_text = instrument_text.rsplit(".", 1)
    else:
        symbol_text, venue_text = str(token.token_id).strip(), DEFAULT_VENUE
    symbol = Symbol(symbol_text)

    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=Venue(venue_text)),
        raw_symbol=symbol,
        asset_class=AssetClass.ALTERNATIVE,
        currency=USDC,
        price_precision=price_increment.precision,
        size_precision=quantity_increment.precision,
        price_increment=price_increment,
        size_increment=quantity_increment,
        activation_ns=_unix_ns(pair.start_ts),
        expiration_ns=_unix_ns(pair.end_ts),
        ts_event=ts_init_ns,
        ts_init=ts_init_ns,
        min_quantity=Quantity.from_str(f"{minimum:g}"),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        outcome=token.side.value,
        description=pair.market_slug or pair.market_id or token.token_id,
        info={
            "condition_id": pair.condition_id,
            "market_slug": pair.market_slug,
            "asset": pair.asset,
            "timeframe": pair.timeframe,
            "token_id": token.token_id,
            "side": token.side.value,
            "tick_size": tick,
            "min_order_size": minimum,
        },
    )
