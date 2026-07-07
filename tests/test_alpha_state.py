"""
Input: __future__, __future__.annotations, collections, collections.deque, datetime, datetime.UTC, datetime.datetime, polysignal_lab.alpha.state, polysignal_lab.alpha.state.json_safe_state, polysignal_lab.alpha.state.restore_utc_datetime
Output: test_json_safe_state_encodes_domain_values_deterministically, test_restore_utc_datetime_requires_iso_string, test_json_safe_state_normalizes_aware_non_utc_datetime_to_utc
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from polysignal_lab.alpha.state import json_safe_state, restore_utc_datetime
from polysignal_lab.domain.enums import Side


def test_json_safe_state_encodes_domain_values_deterministically() -> None:
    payload = {
        "side": Side.UP,
        "seen": {"b", "a"},
        "window": deque([1, 2]),
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }

    assert json_safe_state(payload) == {
        "side": "UP",
        "seen": ["a", "b"],
        "window": [1, 2],
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_restore_utc_datetime_requires_iso_string() -> None:
    restored = restore_utc_datetime("2026-01-01T00:00:00+00:00")

    assert restored.tzinfo is not None
    assert restored.isoformat() == "2026-01-01T00:00:00+00:00"


def test_json_safe_state_normalizes_aware_non_utc_datetime_to_utc() -> None:
    from datetime import timedelta, timezone

    aware_non_utc = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert json_safe_state(aware_non_utc) == "2026-01-01T00:00:00+00:00"
