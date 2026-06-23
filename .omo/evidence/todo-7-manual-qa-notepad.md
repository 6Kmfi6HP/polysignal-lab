# Todo 7 Manual QA Notepad

work: complete-prd-old-remove-demo
task: 7. Align Polymarket/Binance data contracts to official public APIs.
status: ready-for-final-gate

## Matrix

| Scenario | Evidence | Result |
| --- | --- | --- |
| Gamma active market discovery paginates, filters active events, and extracts token IDs | `tests/test_market_data.py::test_gamma_active_market_discovery_paginates_filters_and_extracts_token_ids` | PASS |
| Polymarket CLOB REST parses official order book, official `mid_price` midpoint, and spread | `tests/test_market_data.py::test_clob_rest_public_book_mid_and_spread_parsing_handles_official_shapes`; manual fake midpoint probe returned `0.45` with empty headers | PASS |
| Polymarket public `price_changes` updates registry state | `tests/test_websocket_contracts.py::test_polymarket_price_changes_event_updates_registry` | PASS |
| Polymarket public book, best bid/ask, last trade, and lifecycle payloads remain public-contract safe | `tests/test_websocket_contracts.py::test_polymarket_book_best_bid_ask_last_trade_and_lifecycle_events_are_public_contract_safe` | PASS |
| Binance public `bookTicker` updates spot registry state | `tests/test_websocket_contracts.py::test_binance_bookticker_updates_spot_registry` | PASS |
| Malformed public WebSocket payloads are ignored without crash | `tests/test_websocket_contracts.py::test_malformed_public_market_events_are_ignored_without_crash` | PASS |
| Public payload text is inert and not executed | `tests/test_websocket_contracts.py::test_polymarket_public_payload_text_is_not_executed`; `/tmp/polysignal_prompt_injection` absent | PASS |
| Authenticated/trading surfaces absent | Forbidden-pattern grep over `src/polysignal_lab/data` and `src/polysignal_lab/app` | PASS |
| No live market-data websocket/process leak | Ancestor-aware process scan in task evidence | PASS |

## Notes

- Official CLOB midpoint source checked: `https://docs.polymarket.com/api-reference/data/get-midpoint-price`, 200 response field `mid_price`.
- Prior cleanup probe failures in `.omo/evidence/task-7-complete-prd-old-remove-demo.txt` self-matched their own shell command text and are superseded by the final ancestor-aware cleanup pass.
- No `.env` file was read.
