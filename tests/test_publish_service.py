"""
Input: pytest, factories, factories.sample_paper_trade_result, polysignal_lab.app.services.publish_service, polysignal_lab.app.services.publish_service.PublishService, polysignal_lab.domain.paper_result, polysignal_lab.domain.paper_result.InvalidPaperTradeResultRow
Output: test_publish_service_health_starts_ok, test_deliver_daily_report_uses_durable_idempotency_key, test_publish_signal_persists_publish_audit, test_publish_paper_result_rejects_invalid_payload, test_publish_nautilus_paper_fill_persists_publish_audit, _Publish, _Formatter, _Publisher, _Persistence, _Signal
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""








import pytest

from factories import sample_paper_trade_result

from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_result import InvalidPaperTradeResultRow


class _Publish:
    status = "dry_run"

    def as_dict(self):
        return {"publish_id": "pub-1", "status": self.status}


class _Formatter:
    def __init__(self) -> None:
        self.last_fill = None

    def signal_message(self, signal, stake_usdc: float) -> str:
        return f"signal {stake_usdc}"

    def nautilus_fill_message(self, fill) -> str:
        self.last_fill = fill
        return f"fill {fill['fill_price']}"

    def result_message(self, result) -> str:
        return f"result {result['paper_trade_id']}"

    def daily_report_message(self, report) -> str:
        return f"report {report['report_id']}"


class _Publisher:
    def __init__(self) -> None:
        self.last: tuple[str, str, str | None] | None = None
        self.last_publish_id: str | None = None

    async def send(
        self,
        message: str,
        message_type: str,
        signal_id: str | None,
        *,
        publish_id: str | None = None,
    ):
        self.last = (message, message_type, signal_id)
        self.last_publish_id = publish_id
        return _Publish()





class _Persistence:
    def __init__(self) -> None:
        self.logs = []
        self.publishes = []

    def append_log(self, stream, payload):
        self.logs.append((stream, payload))

    def insert_telegram_publish(self, payload):
        self.publishes.append(payload)


class _Signal:
    signal_id = "sig-1"


def test_publish_service_health_starts_ok() -> None:
    service = PublishService(_Formatter(), _Publisher(), _Persistence())

    assert service.health()["status"] == "ok"


async def test_deliver_daily_report_uses_durable_idempotency_key() -> None:
    publisher = _Publisher()
    service = PublishService(_Formatter(), publisher, _Persistence())

    await service.deliver_daily_report(
        {"report_id": "dr-1", "revision": 2},
        idempotency_key="daily_report:2026-07-13:r2",
    )

    assert publisher.last == ("report dr-1", "daily_report_correction", None)
    assert publisher.last_publish_id == "daily_report:2026-07-13:r2"


async def test_publish_signal_persists_publish_audit() -> None:
    persistence = _Persistence()
    publisher = _Publisher()
    service = PublishService(_Formatter(), publisher, persistence)

    publish = await service.publish_signal(_Signal(), stake_usdc=5.0)

    assert publish.status == "dry_run"
    assert publisher.last == ("signal 5.0", "signal", "sig-1")
    assert persistence.logs == [("telegram_publishes", {"publish_id": "pub-1", "status": "dry_run"})]
    assert persistence.publishes == [{"publish_id": "pub-1", "status": "dry_run"}]


async def test_publish_paper_result_rejects_invalid_payload() -> None:
    persistence = _Persistence()
    publisher = _Publisher()
    service = PublishService(_Formatter(), publisher, persistence)

    with pytest.raises(InvalidPaperTradeResultRow):
        await service.publish_paper_result(
            sample_paper_trade_result(paper_trade_id="pt-invalid", shares="NaN")
        )

    assert publisher.last is None
    assert persistence.logs == []
    assert persistence.publishes == []


async def test_publish_nautilus_paper_fill_persists_publish_audit() -> None:
    persistence = _Persistence()
    publisher = _Publisher()
    formatter = _Formatter()
    service = PublishService(formatter, publisher, persistence)

    publish = await service.publish_nautilus_paper_fill(
        {"signal_id": "sig-fill-1", "fill_price": 0.5}
    )

    assert publish.status == "dry_run"
    assert publisher.last == ("fill 0.5", "nautilus_paper_fill", "sig-fill-1")
    assert formatter.last_fill is not None
    assert formatter.last_fill["fill_price"] == 0.5
    assert persistence.logs == [("telegram_publishes", {"publish_id": "pub-1", "status": "dry_run"})]
    assert persistence.publishes == [{"publish_id": "pub-1", "status": "dry_run"}]


async def test_publish_nautilus_paper_fill_normalizes_projected_rows() -> None:
    persistence = _Persistence()
    publisher = _Publisher()
    formatter = _Formatter()
    market = Market(
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(
                token_id="up-token",
                side=Side.UP,
                outcome_name="Up",
                market_id="market-1",
            )
        ],
    )
    service = PublishService(
        formatter,
        publisher,
        persistence,
        market_lookup=lambda _fill: market,
    )

    publish = await service.publish_nautilus_paper_fill(
        {
            "trade_id": "T-001",
            "order_id": "C-001",
            "instrument_id": "up-token.POLYMARKET",
            "price": "0.5",
            "quantity": "10.0",
            "metrics": {
                "signal_id": "sig-fill-1",
                "strategy": "ptb_diff",
            },
        }
    )

    assert publish.status == "dry_run"
    assert publisher.last == ("fill 0.5", "nautilus_paper_fill", "sig-fill-1")
    assert formatter.last_fill is not None
    assert formatter.last_fill["paper_fill_id"] == "T-001"
    assert formatter.last_fill["paper_order_id"] == "C-001"
    assert formatter.last_fill["token_id"] == "up-token"
    assert formatter.last_fill["fill_price"] == 0.5
    assert formatter.last_fill["shares"] == 10.0
    assert formatter.last_fill["stake_usdc"] == 5.0
    assert formatter.last_fill["asset"] == "BTC"
    assert formatter.last_fill["timeframe"] == "5m"
    assert formatter.last_fill["market_id"] == "market-1"
    assert formatter.last_fill["market_slug"] == "btc-updown-5m"
    assert formatter.last_fill["side"] == "UP"
