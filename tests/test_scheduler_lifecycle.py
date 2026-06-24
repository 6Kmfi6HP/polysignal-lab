from polysignal_lab.app.scheduler import PolySignalScheduler
import pytest

from polysignal_lab.app.services.runtime_service import ServiceSupervisor


class _StartedService:
    name = "started"

    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    def health(self):
        return {"name": self.name, "status": "ok", "metrics": {}}



def test_scheduler_exposes_services_and_supervisor(settings, tmp_path) -> None:
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    names = [service.name for service in scheduler.services]

    assert "persistence" in names
    assert "market_universe" in names
    assert "book_feed" in names
    assert "spot_feed" in names
    assert scheduler.supervisor.services == scheduler.services


async def test_scheduler_stops_started_services_when_startup_fails(settings, tmp_path) -> None:
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    started = _StartedService()
    scheduler.services = [started]
    scheduler.supervisor = ServiceSupervisor(scheduler.services)

    async def fail_restore() -> None:
        raise RuntimeError("restore failed")

    scheduler._restore_wallet_state = fail_restore

    with pytest.raises(RuntimeError, match="restore failed"):
        await scheduler.run()

    assert started.events == ["start", "stop"]
