"""Bridge Polymarket market-WS `feed_resumed` logs into strategy recovery state.

Today the adapter only logs resume (JSONL under `logging.directory`); it does
not emit a Python-visible CustomData event. The evaluation heartbeat polls new
JSONL lines for `feed_resumed ... connection_epoch=N` and clears
`global_book_recovery_epoch_at` so A3 can open one new bounded refresh batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Protocol

from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
)

_FEED_RESUMED_EPOCH_RE = re.compile(
    r"\bfeed_resumed\b.*\bconnection_epoch=(?P<epoch>\d+)",
)
_NAUTILUS_JSONL_GLOB = "PolySignal-Nautilus-*.jsonl"


class _FeedResumeStrategy(Protocol):
    _subscription_state: MarketSubscriptionState
    _runtime_log_directory: str | None
    _feed_resume_log_cursor: FeedResumeLogCursor | None


@dataclass
class FeedResumeLogCursor:
    """Byte-offset cursor over Nautilus runtime JSONL files."""

    directory: Path
    offsets: dict[str, int] = field(default_factory=dict)

    @classmethod
    def starting_at_end(cls, directory: Path) -> FeedResumeLogCursor:
        cursor = cls(directory=directory)
        for path in _nautilus_jsonl_paths(directory):
            try:
                cursor.offsets[str(path)] = path.stat().st_size
            except OSError:
                continue
        return cursor

    def drain_connection_epochs(self) -> tuple[int, ...]:
        epochs: list[int] = []
        for path in _nautilus_jsonl_paths(self.directory):
            key = str(path)
            offset = self.offsets.get(key, 0)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < offset:
                # Rotated/truncated; reread from start.
                offset = 0
            if size == offset:
                self.offsets[key] = offset
                continue
            try:
                with path.open("rb") as handle:
                    _ = handle.seek(offset)
                    chunk = handle.read()
            except OSError:
                continue
            # Keep a trailing partial line unconsumed until the next poll.
            split_at = chunk.rfind(b"\n")
            if split_at < 0:
                continue
            complete = chunk[: split_at + 1]
            self.offsets[key] = offset + len(complete)
            epochs.extend(_epochs_from_jsonl_chunk(complete))
        return tuple(epochs)


def _nautilus_jsonl_paths(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(sorted(directory.glob(_NAUTILUS_JSONL_GLOB)))


def _epochs_from_jsonl_chunk(chunk: bytes) -> list[int]:
    epochs: list[int] = []
    text = chunk.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or "feed_resumed" not in line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # Partial trailing line at EOF; ignore until the next poll completes it.
            continue
        if not isinstance(payload, dict):
            continue
        message = payload.get("message")
        if not isinstance(message, str):
            continue
        match = _FEED_RESUMED_EPOCH_RE.search(message)
        if match is None:
            continue
        epochs.append(int(match.group("epoch")))
    return epochs


def record_feed_resumed(strategy: _FeedResumeStrategy, *, connection_epoch: int) -> None:
    """Observe a feed resume; always reopen the global recovery epoch.

    Clears ``global_book_recovery_epoch_at`` inline (same effect as
    ``lifecycle.note_feed_resumed``) so this module does not import lifecycle
    and create a basedpyright import cycle.
    """
    state = strategy._subscription_state
    previous = state.last_observed_connection_epoch
    epoch = int(connection_epoch)
    if previous is None or epoch > previous:
        state.last_observed_connection_epoch = epoch
    state.global_book_recovery_epoch_at = None


def poll_feed_resume_from_logs(strategy: _FeedResumeStrategy) -> bool:
    """Drain new JSONL `feed_resumed` lines; return True if recovery was reopened."""
    cursor = getattr(strategy, "_feed_resume_log_cursor", None)
    if cursor is None:
        directory = getattr(strategy, "_runtime_log_directory", None)
        if not directory:
            return False
        cursor = FeedResumeLogCursor.starting_at_end(Path(directory))
        strategy._feed_resume_log_cursor = cursor  # type: ignore[misc]
    epochs = cursor.drain_connection_epochs()
    if not epochs:
        return False
    for epoch in epochs:
        record_feed_resumed(strategy, connection_epoch=epoch)
    return True
