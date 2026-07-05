from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TypeAlias, cast

JsonValue: TypeAlias = str | int | float | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


class StateSchemaError(ValueError):
    pass


def state_key(strategy_name: str, version: int = 1) -> str:
    return f"polysignal.{strategy_name}.state.v{version}"


def encode_state(strategy_name: str, payload: Mapping[str, JsonValue], version: int = 1) -> dict[str, bytes]:
    key = state_key(strategy_name, version)
    body: JsonObject = {"schema_version": version, "payload": dict(payload)}
    return {key: json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")}


def decode_state(strategy_name: str, state: Mapping[str, bytes], version: int = 1) -> JsonObject:
    key = state_key(strategy_name, version)
    same_strategy_prefix = f"polysignal.{strategy_name}.state.v"
    unknown_keys = sorted(name for name in state if name.startswith(same_strategy_prefix) and name != key)
    if unknown_keys:
        raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {unknown_keys[0]}")
    if key not in state:
        return {"migration_reasons": [f"missing {key}"]}

    raw_obj = cast(object, json.loads(state[key].decode("utf-8")))
    if not isinstance(raw_obj, dict):
        raise StateSchemaError(f"Invalid state envelope for {strategy_name}")
    raw = cast(dict[str, object], raw_obj)
    schema_version = raw.get("schema_version")
    if schema_version != version:
        raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {schema_version}")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise StateSchemaError(f"Invalid state payload for {strategy_name}")
    return cast(JsonObject, payload)
