# 06 Public Market Data Capability Boundary Design

**Status:** Approved
**Scope:** One standalone architecture change. Do not execute with specs 01-05 or 07-08 in the same implementation batch.
**Goal:** Make the read-only Polymarket boundary enforceable by construction, not only by substring safety scanning.

## Problem

PolySignal's safety model intentionally forbids secret material, authenticated Polymarket clients, live market actions, and redemption. This is enforced through config validation, environment key rejection, and a safety scanner. The current CLOB REST adapter imports `py_clob_client_v2.ClobClient` through a read-only alias and constructs it without credentials. That is acceptable today, but future SDK changes could accidentally expose order methods to scheduler or strategies.

`PolySignalScheduler` currently constructs `PolymarketCLOBRestClient` directly, so this spec must introduce a protocol dependency at scheduler boundaries rather than only wrapping lower-level REST calls.

The existing adapter also accepts and stores a public `sdk_client`, so a wrapper must remove that public escape hatch instead of forwarding it.

Official SDK direction separates public and secure clients. PolySignal should mirror that separation internally.

## Non-goals

- No migration to Polymarket beta SDK in this spec.
- No live trading capability.
- No weakening of existing safety scan.
- No broad dependency injection framework.

## Target behavior

1. Application code depends on a narrow `PublicMarketDataClient` protocol, not an SDK client.
2. `PolySignalScheduler` does not construct or expose `PolymarketCLOBRestClient` directly; scheduler paths receive a protocol implementation or factory.
3. Only one module may import Polymarket SDK client types.
4. That module refuses credentials/key material at construction.
5. The adapter does not expose SDK objects through public constructor parameters, attributes, or methods, including any `sdk_client` capability.
6. Scheduler, strategies, paper simulation, and dashboard cannot access order/cancel/redeem methods.
7. Safety scan remains as a second-line defense but no longer carries the entire safety burden.
8. Tests prove forbidden imports/symbols are absent outside the adapter boundary.

## Proposed interface

```python
class PublicMarketDataClient(Protocol):
    async def get_book(self, token_id: str) -> OrderBook: ...
    async def get_books(self, token_ids: list[str]) -> list[OrderBook]: ...
    async def get_mid(self, token_id: str) -> float | None: ...
    async def get_spread(self, token_id: str) -> float | None: ...
```

Implementation can live in `src/polysignal_lab/data/public_market_data_client.py` and wrap the existing `PolymarketCLOBRestClient` or replace it gradually, but any wrapped SDK instance must stay private and must not be injectable or retrievable through public adapter APIs.

## Boundary rules

Allowed:

- `src/polysignal_lab/data/polymarket_clob_rest.py` or successor adapter importing SDK public client.
- Read-only REST endpoints: `/book`, `/books`, `/midpoint`, `/spread`, public market metadata.

Forbidden outside the adapter and on the adapter's public surface:

- direct SDK client imports;
- secure/auth client imports;
- private key/API key/passphrase/funder config;
- order, cancel, redeem, allowance, user-channel methods.
- public constructor parameters, attributes, or methods that accept, return, or expose SDK client objects, including `sdk_client`.

## Safety tests

Add/extend safety tests to assert:

- no module outside the adapter imports SDK client names, across non-adapter production source and deliberate forbidden fixtures;
- adapter constructor does not accept credential fields;
- adapter public constructor, attributes, and methods do not expose SDK objects or `sdk_client` capability;
- blocked trading symbols remain rejected;
- environment validation still rejects secret-like keys.

## Acceptance criteria

- `PolySignalScheduler` receives only the public protocol/adapter or a protocol factory and no longer constructs/exposes `PolymarketCLOBRestClient` directly.
- Existing CLOB read paths still work.
- Safety scan passes, and import-boundary policy tests cover both non-adapter source and deliberate forbidden fixtures.
- A deliberate forbidden SDK import in a non-adapter test fixture is detected by policy test.
- No authenticated endpoint, credential field, or public SDK client escape hatch is introduced.

## Test strategy

- Unit tests with fake `PublicMarketDataClient`.
- Safety policy tests over source tree plus deliberate violating fixtures outside the adapter boundary.
- Existing `tests/test_safety.py` remains passing.
- Bounded read-only smoke still contacts only public endpoints.

## Rollout

1. Introduce protocol and move SDK construction behind the adapter boundary.
2. Update scheduler to use protocol type.
3. Add import-boundary tests.
4. Keep current substring scan until AST/import policy is mature.
5. Document the boundary in code comments near the adapter, not in a separate operations manual.