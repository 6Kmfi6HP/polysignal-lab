from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock


BOOK_RECOVERY_DEDUP_SEC = 60.0


def _utc(value: datetime) -> datetime:
    observed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return observed.astimezone(UTC)


@dataclass(slots=True)
class BookRecoveryCoordinator:
    """Coalesce strategy recovery intents for one shared market-data runtime."""

    dedup_sec: float = BOOK_RECOVERY_DEDUP_SEC
    _claims_by_key: dict[str, tuple[datetime, object]] = field(
        default_factory=dict,
        init=False,
    )
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def claim(
        self,
        instrument_ids: Sequence[object],
        *,
        now: datetime,
    ) -> BookRecoveryClaim:
        observed = _utc(now)
        token = object()
        claimed: list[object] = []
        with self._lock:
            expired = tuple(
                key
                for key, (claimed_at, _token) in self._claims_by_key.items()
                if (observed - claimed_at).total_seconds() > self.dedup_sec
            )
            for key in expired:
                _ = self._claims_by_key.pop(key, None)
            for instrument_id in instrument_ids:
                key = str(instrument_id)
                active = self._claims_by_key.get(key)
                if (
                    active is not None
                    and (observed - active[0]).total_seconds() <= self.dedup_sec
                ):
                    continue
                self._claims_by_key[key] = (observed, token)
                claimed.append(instrument_id)
        return BookRecoveryClaim(tuple(claimed), token)

    def release(
        self,
        claim: BookRecoveryClaim,
        instrument_ids: Sequence[object] | None = None,
    ) -> None:
        targets = claim.instrument_ids if instrument_ids is None else instrument_ids
        with self._lock:
            for instrument_id in targets:
                key = str(instrument_id)
                active = self._claims_by_key.get(key)
                if active is not None and claim.owns(active[1]):
                    _ = self._claims_by_key.pop(key, None)

    def rearm(self, instrument_ids: Sequence[object]) -> None:
        with self._lock:
            for instrument_id in instrument_ids:
                key = str(instrument_id)
                _ = self._claims_by_key.pop(key, None)


@dataclass(frozen=True, slots=True)
class BookRecoveryClaim:
    instrument_ids: tuple[object, ...]
    _token: object = field(repr=False, compare=False)

    def owns(self, token: object) -> bool:
        return self._token is token


_runtime_book_recovery_coordinator: BookRecoveryCoordinator | None = None


def bind_runtime_book_recovery_coordinator(
    coordinator: BookRecoveryCoordinator | None,
) -> None:
    """Bind or clear the process-local coordinator for importable strategies."""
    global _runtime_book_recovery_coordinator
    _runtime_book_recovery_coordinator = coordinator


def runtime_book_recovery_coordinator() -> BookRecoveryCoordinator | None:
    return _runtime_book_recovery_coordinator
