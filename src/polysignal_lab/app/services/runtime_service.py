"""
Input: __future__, __future__.annotations, typing, typing.Any, typing.Protocol
Output: RuntimeService, ServiceSupervisor
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from typing import Any, Protocol


class RuntimeService(Protocol):
    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def health(self) -> Any: ...


class ServiceSupervisor:
    def __init__(self, services: list[RuntimeService]) -> None:
        self.services = services
        self.stop_order: list[str] = []

    async def start_all(self) -> None:
        for service in self.services:
            await service.start()

    async def stop_all(self) -> None:
        for service in reversed(self.services):
            await service.stop()
            self.stop_order.append(service.name)
