"""
Input: __future__, __future__.annotations, polysignal_lab.nautilus_runtime.live_node, polysignal_lab.nautilus_runtime.live_node.SANDBOX_EXEC_CLIENT_ID
Output: test_default_runtime_sandbox_client_id_stays_distinct_from_polymarket_venue
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from polysignal_lab.nautilus_runtime.live_node import SANDBOX_EXEC_CLIENT_ID


def test_default_runtime_sandbox_client_id_stays_distinct_from_polymarket_venue() -> None:
    assert SANDBOX_EXEC_CLIENT_ID != "POLYMARKET"
