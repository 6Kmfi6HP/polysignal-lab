
from polysignal_lab.app.services.publish_service import PublishService


class _Publish:
    status = "dry_run"

    def as_dict(self):
        return {"publish_id": "pub-1", "status": self.status}


class _Formatter:
    def signal_message(self, signal, stake_usdc: float) -> str:
        return f"signal {stake_usdc}"
    def nautilus_fill_message(self, fill) -> str:
        return f"fill {fill['fill_price']}"


class _Publisher:
    async def send(self, message: str, message_type: str, signal_id: str | None):
        self.last = (message, message_type, signal_id)
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


async def test_publish_signal_persists_publish_audit() -> None:
    persistence = _Persistence()
    publisher = _Publisher()
    service = PublishService(_Formatter(), publisher, persistence)

    publish = await service.publish_signal(_Signal(), stake_usdc=5.0)

    assert publish.status == "dry_run"
    assert publisher.last == ("signal 5.0", "signal", "sig-1")
    assert persistence.logs == [("telegram_publishes", {"publish_id": "pub-1", "status": "dry_run"})]
    assert persistence.publishes == [{"publish_id": "pub-1", "status": "dry_run"}]


async def test_publish_nautilus_paper_fill_persists_publish_audit() -> None:
    persistence = _Persistence()
    publisher = _Publisher()
    service = PublishService(_Formatter(), publisher, persistence)

    publish = await service.publish_nautilus_paper_fill(
        {"signal_id": "sig-fill-1", "fill_price": 0.5}
    )

    assert publish.status == "dry_run"
    assert publisher.last == ("fill 0.5", "nautilus_paper_fill", "sig-fill-1")
    assert persistence.logs == [("telegram_publishes", {"publish_id": "pub-1", "status": "dry_run"})]
    assert persistence.publishes == [{"publish_id": "pub-1", "status": "dry_run"}]
