"""
Input: polysignal_lab.app.scheduler, polysignal_lab.app.scheduler.PolySignalScheduler, pytest, polysignal_lab.app.services.runtime_service, polysignal_lab.app.services.runtime_service.ServiceSupervisor
Output: test_scheduler_exposes_services_and_supervisor, test_scheduler_stops_started_services_when_startup_fails, test_scheduler_does_not_register_telegram_bot_by_default, test_scheduler_registers_telegram_bot_in_init_when_interactive_enabled, _StartedService
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





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

    async def fail_refresh() -> None:
        raise RuntimeError("refresh failed")

    scheduler.refresh_markets_once = fail_refresh

    with pytest.raises(RuntimeError, match="refresh failed"):
        await scheduler.run()

    assert started.events == ["start", "stop"]


def test_scheduler_does_not_register_telegram_bot_by_default(settings, tmp_path) -> None:
    settings.telegram.interactive_enabled = False

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    names = [service.name for service in scheduler.services]
    assert "telegram_bot" not in names
    assert scheduler.supervisor.services == scheduler.services


def test_scheduler_registers_telegram_bot_in_init_when_interactive_enabled(settings, tmp_path) -> None:
    settings.telegram.interactive_enabled = True
    settings.telegram.interactive_allowed_chat_ids = (123,)

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    names = [service.name for service in scheduler.services]
    assert "telegram_bot" in names
    assert names.index("publish") < names.index("telegram_bot") < names.index("health")
    assert scheduler.supervisor.services == scheduler.services
    assert any(service.name == "telegram_bot" for service in scheduler.health_service.services)
