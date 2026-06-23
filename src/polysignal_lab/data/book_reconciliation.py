from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class BookEpochState:
    token_id: str
    epoch: int
    has_snapshot: bool
    stale_reason: str | None
    last_hash: str | None
    last_source_timestamp: datetime | None
    last_received_at: datetime | None
