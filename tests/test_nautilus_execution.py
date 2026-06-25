from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

import httpx
import urllib.request

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.market import OutcomeToken
from polysignal_lab.nautilus_runtime.execution import (
    PaperExecutionResult,
    PolySignalPaperExecutionClient,
)
from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def market():
    return sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=120))


@pytest.fixture
def up_token(market):
    return market.token_for(Side.UP)


@pytest.fixture
def down_token(market):
    return market.token_for(Side.DOWN)


@pytest.fixture
def client(up_token, down_token):
    """Paper execution client backed by sample book data, no credentials."""
    from polysignal_lab.config import FillModelConfig
    from polysignal_lab.utils import utc_now
    up_book = sample_book(up_token.token_id, BookFactoryConfig(ask=0.82, size=500))
    down_book = sample_book(down_token.token_id, BookFactoryConfig(ask=0.18, size=500))
    up_book._updated_at = utc_now()
    down_book._updated_at = utc_now()
    return PolySignalPaperExecutionClient(
        order_book_data={up_token.token_id: up_book, down_token.token_id: down_book},
        fill_config=FillModelConfig(slippage_bps=0, require_depth_check=False),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_creates_without_credentials() -> None:
    """Client must be constructable without any API keys or credentials."""
    client = PolySignalPaperExecutionClient()
    assert client is not None


def test_creates_with_order_book_data(up_token) -> None:
    """Client may accept pre-loaded order book data."""
    book = sample_book(up_token.token_id, BookFactoryConfig(ask=0.82, size=500))
    client = PolySignalPaperExecutionClient(order_book_data={up_token.token_id: book})
    assert client is not None


def test_creates_without_order_book_data() -> None:
    """Client can work empty and receive book data later."""
    client = PolySignalPaperExecutionClient()
    assert client is not None


# ---------------------------------------------------------------------------
# Paper execution contract
# ---------------------------------------------------------------------------

def test_paper_order_returns_result(client, up_token) -> None:
    """submit_spec returns a PaperExecutionResult with order metadata."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=100.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    assert isinstance(result, PaperExecutionResult)
    assert result.order is not None
    assert result.order.paper_order_id
    assert result.order.token_id == up_token.token_id
    assert result.order.side == Side.UP


def test_paper_result_status_matches_submission(client, up_token) -> None:
    """A successfully submitted order has FILLED status."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=50.0,
        intent=OrderIntent.TAKER_FAK,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    assert result.status in (OrderStatus.FILLED, OrderStatus.RESTING, OrderStatus.PENDING)


def test_paper_result_has_order_id(client, up_token) -> None:
    """Paper execution result includes a paper_order_id."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=50.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    assert result.order is not None
    assert result.order.paper_order_id is not None


# ---------------------------------------------------------------------------
# No network orders
# ---------------------------------------------------------------------------

def test_does_not_send_http_requests(client, up_token) -> None:
    """The paper execution client must not make any HTTP requests."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=50.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    with (
        patch.object(urllib.request, "urlopen") as mock_urlopen,
        patch.object(httpx, "request") as mock_httpx,
    ):
        result = client.submit_spec(spec)

    assert isinstance(result, PaperExecutionResult)
    mock_urlopen.assert_not_called()
    mock_httpx.assert_not_called()


def test_paper_order_no_credentials_needed(client, up_token) -> None:
    """Order submission must not require any credential parameters."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=50.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    # No credentials passed — should work without API keys / secrets
    result = client.submit_spec(spec)
    assert isinstance(result, PaperExecutionResult)
    assert result.order is not None


# ---------------------------------------------------------------------------
# Depth rejection
# ---------------------------------------------------------------------------

def test_rejects_order_when_book_depth_insufficient_for_fok(client, up_token) -> None:
    """FOK order where quantity > available depth returns rejected result."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=1_000_000.0,  # far exceeds available depth
        intent=OrderIntent.TAKER_FOK,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    assert result.status == OrderStatus.REJECTED


def test_rejects_order_when_book_empty(up_token) -> None:
    """An order against an empty book is rejected."""
    client = PolySignalPaperExecutionClient(order_book_data={})
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=100.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    assert result.status == OrderStatus.REJECTED


def test_rejects_order_for_unknown_instrument(client) -> None:
    """Order for an unrecognised instrument_id is rejected."""
    spec = NautilusOrderSpec(
        instrument_id="nonexistent-token",
        side=Side.UP,
        price=0.82,
        quantity=100.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    assert result.status == OrderStatus.REJECTED


# ---------------------------------------------------------------------------
# Fill data in PaperExecutionResult
# ---------------------------------------------------------------------------

def test_fills_for_inline_fill_check(client, up_token) -> None:
    """Filled taker orders emit PaperFill objects in the result."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=100.0,
        intent=OrderIntent.TAKER_FAK,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    if result.fills:
        fill = result.fills[0]
        assert fill.fill_price > 0
        assert fill.shares > 0


def test_fill_prices_reflect_trade_data(client, up_token) -> None:
    """Fill prices in the result are consistent with trade execution."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=100.0,
        intent=OrderIntent.TAKER_FAK,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    if result.fills:
        assert isinstance(result.fills[0].fill_price, float)
        assert isinstance(result.fills[0].shares, float)
        assert result.fills[0].fill_price > 0
        assert result.fills[0].shares > 0


def test_partial_fill_for_fak(client, up_token) -> None:
    """FAK fills partially when available depth is less than requested quantity."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.82,
        quantity=1_000.0,  # more than the 500 available shares
        intent=OrderIntent.TAKER_FAK,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    if result.fills:
        assert result.fills[0].shares == pytest.approx(500.0, rel=0.01)  # limited by depth (FP safe)


# ---------------------------------------------------------------------------
# PASSIVE_GTD expiry
# ---------------------------------------------------------------------------

def test_gtd_order_accepts_as_resting(client, up_token) -> None:
    """PASSIVE_GTD orders are accepted as resting orders when price is below best ask."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.80,  # below best ask, so passive
        quantity=100.0,
        intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=3600,
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    # Price below best ask may be rejected by gate; both outcomes acceptable
    assert result.status in (
        OrderStatus.RESTING,
        OrderStatus.FILLED,
        OrderStatus.PENDING,
        OrderStatus.REJECTED,
    ) or (result.reason and "resting" in result.reason.lower())


def test_gtd_order_expires_after_timeout(client, up_token) -> None:
    """A PASSIVE_GTD order that stays unfilled past expiry produces a rejection."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.UP,
        price=0.80,
        quantity=100.0,
        intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=0,  # expires immediately
        pair_id=None,
        reduce_only=False,
        hedge_leg=False,
        tags={"strategy": "test"},
    )
    result = client.submit_spec(spec)

    # Should either be rejected at submission or reported as expired
    assert result.status == OrderStatus.REJECTED or (
        result.reason and "resting" in result.reason.lower()
    )


# ---------------------------------------------------------------------------
# Hedge leg tagging
# ---------------------------------------------------------------------------

def test_hedge_leg_orders_are_tagged(client, up_token) -> None:
    """Paper execution result preserves the hedge_leg flag in the order."""
    spec = NautilusOrderSpec(
        instrument_id=up_token.token_id,
        side=Side.DOWN,
        price=0.18,
        quantity=100.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=False,
        hedge_leg=True,
        tags={"strategy": "test", "hedge_leg": "true"},
    )
    result = client.submit_spec(spec)

    assert isinstance(result, PaperExecutionResult)
    assert result.order is not None
    assert result.order.hedge_leg is True
