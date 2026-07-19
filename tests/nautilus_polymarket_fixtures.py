"""
Input: datetime, nautilus_trader
Output: polymarket_binary_instrument, rust_shaped_polymarket_binary_instrument
Pos: Test Layer - Nautilus Polymarket fixtures

🔄 Self-reference: When this file changes, update this header and tests/FOLDER_INDEX.md
"""

from datetime import UTC, datetime, timedelta

from nautilus_trader.core import nautilus_pyo3 as pyo3


_DEFAULT_EVENT_START = datetime(2026, 7, 18, 12, tzinfo=UTC)
_DEFAULT_EVENT_END = datetime(2026, 7, 18, 12, 5, tzinfo=UTC)


def polymarket_binary_instrument(
    token_id: str,
    outcome: str,
    *,
    condition_id: str = "0xcondition1",
    market_id: str = "market-1",
    event_start: datetime = _DEFAULT_EVENT_START,
    event_end: datetime = _DEFAULT_EVENT_END,
    active: bool = True,
    closed: bool = False,
    gamma_overrides: dict[str, object] | None = None,
) -> object:
    slug = f"btc-updown-5m-{int(event_start.timestamp())}"
    gamma_original: dict[str, object] = {
        "id": market_id,
        "conditionId": condition_id,
        "question": "Bitcoin Up or Down?",
        "slug": slug,
        "eventSlug": slug,
        "eventStartTime": event_start.isoformat().replace("+00:00", "Z"),
        "endDate": event_end.isoformat().replace("+00:00", "Z"),
        "active": active,
        "closed": closed,
    }
    if gamma_overrides:
        gamma_original.update(gamma_overrides)
    info = {
        "condition_id": condition_id,
        "question": "Bitcoin Up or Down?",
        "minimum_tick_size": "0.01",
        "end_date_iso": event_end.isoformat().replace("+00:00", "Z"),
        "_gamma_original": gamma_original,
    }
    price_increment = pyo3.Price.from_str("0.01")
    size_increment = pyo3.Quantity.from_str("0.000001")
    return pyo3.BinaryOption(
        instrument_id=pyo3.InstrumentId.from_str(f"{condition_id}-{token_id}.POLYMARKET"),
        raw_symbol=pyo3.Symbol(token_id),
        asset_class=pyo3.AssetClass.ALTERNATIVE,
        currency=pyo3.Currency.from_str("USDC"),
        activation_ns=0,
        expiration_ns=int(event_end.timestamp() * 1e9),
        price_precision=price_increment.precision,
        size_precision=size_increment.precision,
        price_increment=price_increment,
        size_increment=size_increment,
        ts_event=0,
        ts_init=0,
        outcome=outcome,
        info=info,
    )


def rust_shaped_polymarket_binary_instrument(
    token_id: str,
    outcome: str,
    *,
    condition_id: str = "0xcondition1",
    market_id: str = "719367",
    event_start: datetime = _DEFAULT_EVENT_START,
    event_end: datetime | None = None,
) -> object:
    """BinaryOption matching official Rust Polymarket adapter info keys.

    Official ``build_info_json`` only stores token_id/condition_id/market_id/
    question_id/market_slug/neg_risk — no active/closed/end_date_iso. Lifecycle
    times live on BinaryOption activation_ns/expiration_ns.
    """
    end = event_end or (event_start + timedelta(minutes=5))
    price_increment = pyo3.Price.from_str("0.01")
    size_increment = pyo3.Quantity.from_str("0.000001")
    info = {
        "token_id": token_id,
        "condition_id": condition_id,
        "market_id": market_id,
        "question_id": "0xquestion",
        "market_slug": f"btc-updown-5m-{int(event_start.timestamp())}",
        "neg_risk": False,
    }
    return pyo3.BinaryOption(
        instrument_id=pyo3.InstrumentId.from_str(f"{condition_id}-{token_id}.POLYMARKET"),
        raw_symbol=pyo3.Symbol(token_id),
        asset_class=pyo3.AssetClass.ALTERNATIVE,
        currency=pyo3.Currency.from_str("USDC"),
        activation_ns=int(event_start.timestamp() * 1e9),
        expiration_ns=int(end.timestamp() * 1e9),
        price_precision=price_increment.precision,
        size_precision=size_increment.precision,
        price_increment=price_increment,
        size_increment=size_increment,
        ts_event=0,
        ts_init=0,
        outcome=outcome,
        description="Bitcoin Up or Down?",
        info=info,
    )
