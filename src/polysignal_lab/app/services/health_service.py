"""
Input: __future__, __future__.annotations, typing, typing.Any
Output: HealthService
Pos: Service Layer - Business logic

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from typing import Any


class HealthService:
    """Compatibility health adapter until the spec-04 ComponentHealth contract lands."""

    name = "health"

    def __init__(self, services: list[Any]) -> None:
        self.services = services

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        components = []
        for service in self.services:
            health = service.health()
            components.append(health)
        degraded = any(component.get("status") != "ok" for component in components if isinstance(component, dict))
        return {
            "name": self.name,
            "status": "degraded" if degraded else "ok",
            "metrics": {"components": len(components)},
            "components": components,
        }
