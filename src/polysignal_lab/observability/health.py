from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from polysignal_lab.utils import utc_iso


@dataclass
class HealthRegistry:
    components: dict[str, dict[str, Any]] = field(default_factory=dict)

    def set(self, name: str, status: str, **details: Any) -> None:
        self.components[name] = {"status": status, "updated_at": utc_iso(), **details}

    def snapshot(self) -> dict[str, Any]:
        overall = "OK" if all(v.get("status") == "OK" for v in self.components.values()) else "DEGRADED"
        return {"overall": overall, "components": self.components}
