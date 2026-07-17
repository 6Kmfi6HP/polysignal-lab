"""
Input: __future__, __future__.annotations, json, collections.abc, collections.abc.Mapping, collections.abc.Sequence, typing, typing.TypeAlias, typing.cast
Output: state_key, encode_state, decode_state, save_strategy_state, load_strategy_state, StateSchemaError
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TypeAlias, cast

JsonValue: TypeAlias = str | int | float | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]

STRATEGY_STATE_VERSION = 3


class StateSchemaError(ValueError):
    pass


def state_key(strategy_name: str, version: int = STRATEGY_STATE_VERSION) -> str:
    return f"polysignal.{strategy_name}.state.v{version}"


def encode_state(
    strategy_name: str,
    payload: Mapping[str, JsonValue],
    version: int = STRATEGY_STATE_VERSION,
) -> dict[str, bytes]:
    key = state_key(strategy_name, version)
    body: JsonObject = {"schema_version": version, "payload": dict(payload)}
    return {key: json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")}


def decode_state(
    strategy_name: str,
    state: Mapping[str, bytes],
    version: int = STRATEGY_STATE_VERSION,
) -> JsonObject:
    key = state_key(strategy_name, version)
    same_strategy_prefix = f"polysignal.{strategy_name}.state.v"
    unknown_keys = sorted(
        name
        for name in state
        if name.startswith(same_strategy_prefix)
        and name != key
    )
    if unknown_keys:
        raise StateSchemaError(f"Unsupported state schema for {strategy_name}: {unknown_keys[0]}")
    if key in state:
        return _decode_envelope(strategy_name, state[key], expected_version=version)

    return {"migration_reasons": [f"missing {key}"]}


def _decode_envelope(
    strategy_name: str,
    raw_bytes: bytes,
    *,
    expected_version: int,
) -> JsonObject:
    raw_obj = cast(object, json.loads(raw_bytes.decode("utf-8")))
    if not isinstance(raw_obj, dict):
        raise StateSchemaError(f"Invalid state envelope for {strategy_name}")
    raw = cast(dict[str, object], raw_obj)
    schema_version = raw.get("schema_version")
    if schema_version != expected_version:
        raise StateSchemaError(
            f"Unsupported state schema for {strategy_name}: {schema_version}"
        )
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise StateSchemaError(f"Invalid state payload for {strategy_name}")
    return cast(JsonObject, payload)


def save_strategy_state(
    strategy_name: str,
    core: object,
) -> dict[str, bytes]:
    saver = getattr(core, "save_state", None)
    alpha_raw = saver() if callable(saver) else {}
    if not isinstance(alpha_raw, Mapping):
        alpha_raw = {}
    payload: dict[str, JsonValue] = {
        "alpha": dict(cast(Mapping[str, JsonValue], alpha_raw)),
    }
    return encode_state(strategy_name, payload)


def load_strategy_state(
    strategy_name: str,
    core: object,
    state: Mapping[str, bytes],
) -> None:
    payload = cast(Mapping[str, object], decode_state(strategy_name, state))
    alpha_raw = payload.get("alpha", {})
    alpha = cast(
        Mapping[str, object],
        alpha_raw if isinstance(alpha_raw, Mapping) else {},
    )
    loader = getattr(core, "load_state", None)
    if callable(loader):
        loader(alpha)
