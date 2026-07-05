from __future__ import annotations

from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID


def test_default_runtime_sandbox_client_id_stays_distinct_from_polymarket_venue() -> None:
    assert PAPER_EXEC_CLIENT_ID != "POLYMARKET"
