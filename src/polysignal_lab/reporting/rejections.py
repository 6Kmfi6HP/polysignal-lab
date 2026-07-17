from __future__ import annotations

from typing import Any

ORDER_REJECTED = "ORDER_REJECTED"


RejectReason = str | int | float | bool | None


def normalize_reject_reason(reason: RejectReason) -> str:
    if not isinstance(reason, str):
        return ORDER_REJECTED
    normalized = reason.strip().upper()
    return normalized or ORDER_REJECTED


def is_rejected_order_payload(
    order: dict[str, Any], metrics: dict[str, Any]
) -> bool:
    status = order.get("status")
    if status == "REJECTED":
        return True
    if status != "CANCELLED":
        return False
    return bool(
        metrics.get("normalized_reason")
        or metrics.get("original_reason")
        or order.get("reject_reason")
    )
