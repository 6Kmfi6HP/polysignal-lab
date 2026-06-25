from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class StateSchemaError(ValueError):
    pass


def state_key(strategy_name: str, version: int = 1) -> str:
    return f"polysignal.{strategy_name}.state.v{version}"


def encode_state(strategy_name: str, payload: Mapping[str, Any], version: int = 1) -> dict[str, bytes]:
    key = state_key(strategy_name, version)
    body = {"schema_version": version, "payload": payload}
    return {key: json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")}


def decode_state(strategy_name: str, state: Mapping[str, bytes], version: int = 1) -> dict[str, Any]:
    key = state_key(strategy_name, version)
    same_strategy_prefix = f"polysignal.{strategy_name}.state.v"
    unknown_keys = sorted(name for name in state if name.startswith(same_strategy_prefix) and name != key)
    if unknown_keys:
        raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {unknown_keys[0]}")
    if key not in state:
        return {"migration_reasons": [f"missing {key}"]}

    raw = json.loads(state[key].decode("utf-8"))
    if raw.get("schema_version") != version:
        raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {raw.get('schema_version')}")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise StateSchemaError(f"Invalid state payload for {strategy_name}")
    return payload
