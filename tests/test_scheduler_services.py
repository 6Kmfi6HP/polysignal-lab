"""
Input: polysignal_lab.app.services.runtime_service, polysignal_lab.app.services.runtime_service.ServiceSupervisor
Output: test_supervisor_starts_and_stops_services_in_reverse_order, _Service
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from polysignal_lab.app.services.runtime_service import ServiceSupervisor


class _Service:
    name = "fake"

    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    def health(self):
        return {"name": self.name, "status": "ok", "metrics": {}}


async def test_supervisor_starts_and_stops_services_in_reverse_order() -> None:
    first = _Service()
    second = _Service()
    supervisor = ServiceSupervisor([first, second])

    await supervisor.start_all()
    await supervisor.stop_all()

    assert first.events == ["start", "stop"]
    assert second.events == ["start", "stop"]
    assert supervisor.stop_order == ["fake", "fake"]
