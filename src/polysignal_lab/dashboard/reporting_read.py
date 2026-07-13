"""
Input: __future__, typing
Output: JsonRow, ReportingReadPort
Pos: Dashboard read boundary

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from typing import Any, Protocol, TypeAlias

JsonRow: TypeAlias = dict[str, Any]


class ReportingReadPort(Protocol):
    def counts(self) -> dict[str, int]: ...

    def recent_system_events(self, limit: int) -> list[JsonRow]: ...

    def latest_health_snapshot(self) -> JsonRow | None: ...

    def strategy_status_rows(self, limit: int) -> list[JsonRow]: ...

    def daily_reports(self, limit: int) -> list[JsonRow]: ...

    def signal_rows(self, limit: int) -> list[JsonRow]: ...

    def rejected_signal_rows(self, limit: int) -> list[JsonRow]: ...

    def paper_order_rows(
        self,
        status: str | None,
        limit: int,
    ) -> list[JsonRow]: ...

    def market_rows(self, limit: int) -> list[JsonRow]: ...

    def paper_position_rows(
        self,
        status: str | None,
        limit: int,
    ) -> list[JsonRow]: ...

    def paper_trade_result_rows(self, limit: int) -> list[JsonRow]: ...

    def strategy_leaderboard(self, limit: int) -> list[JsonRow]: ...
