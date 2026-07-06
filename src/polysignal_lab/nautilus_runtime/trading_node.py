from __future__ import annotations

from collections.abc import Mapping

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
POLYMARKET_CLIENT_ID = "POLYMARKET"


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", None)
    if exec_clients is None and isinstance(config, Mapping):
        exec_clients = config.get("exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")
