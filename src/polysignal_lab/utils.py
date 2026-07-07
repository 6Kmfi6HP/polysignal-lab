"""
Input: __future__, __future__.annotations, hashlib, json, math, re, secrets, datetime, datetime.UTC, datetime.datetime
Output: utc_now, utc_iso, parse_dt, stable_hash, new_id, safe_float, as_decimal, to_jsonable, compact_json, mask_secret
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def utc_iso(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def stable_hash(*parts: object, length: int = 16) -> str:
    raw = ":".join(str(p) for p in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def new_id(prefix: str, *parts: object) -> str:
    ts = utc_now().strftime("%Y%m%d%H%M%S%f")
    suffix = stable_hash(ts, secrets.token_hex(4), *parts, length=8)
    return f"{prefix}_{ts}_{suffix}"


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError, ArithmeticError):
        return default


def as_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _is_dataclass_instance(value: Any) -> bool:
    from dataclasses import is_dataclass

    return is_dataclass(value) and not isinstance(value, type)


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if _is_dataclass_instance(value):
        from dataclasses import asdict

        return to_jsonable(asdict(value))
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return value


def compact_json(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def redact_text(text: str) -> str:
    patterns = [
        r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b",
        r"(?i)(token|secret|password|api[_-]?key)\s*[:=]\s*[^\s]+",
    ]
    out = text
    for pattern in patterns:
        out = re.sub(pattern, lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", out)
    return out
