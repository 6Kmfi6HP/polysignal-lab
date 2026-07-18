## 📁 nautilus_runtime/

**Architecture**:
- Application code

**Files**:
- `strategy_builder.py` - Exports AlphaCoreRegistry
- `state.py` - Exports state_key and 5 more
- `spot_anchor_state.py` - Exports SpotAnchorState
- `signal_notifications.py` - Exports _AcceptedSignalJob and 3 more
- `runtime_registration.py` - Exports enabled_strategy_names and 1 more
- `runtime_context_factory.py` - Exports validate_native_runtime_settings and 2 more
- `runtime_configs.py` - Exports importable_config_dict and 2 more
- `projections.py` - Exports project_order_event and 4 more
- `polymarket_slugs.py` - Exports build_polymarket_updown_event_slugs
- `polymarket_adapter.py` - Exports PolymarketEnumParser
- `order_plan.py` - Exports build_order_spec and 13 more
- `order_mapping.py` - Exports order_spec_from_decision
- `optional_imports.py` - Exports load_live_runtime_symbols and 1 more
- `observability_persistence.py` - Exports persistence_class_for_table and 9 more
- `observability.py` - Exports _TelemetryEvent and 3 more
- `node_signals.py` - Application code
- `node_shared.py` - Application code
- `node_probes.py` - Application code
- `node_lifecycle.py` - Application code
- `node_crash.py` - Application code
- `node_cli.py` - Exports run_nautilus_cli_async
- `node_builder_components.py` - Exports create_market_projection_components and 3 more
- `node_builder.py` - Exports build_runtime_node and 4 more
- `node.py` - Exports run_nautilus_cli and 1 more
- `native_strategy_exit.py` - Exports thresholds_from_metrics and 2 more
- `native_strategy.py` - Exports PolySignalNativeStrategy
- `native_order.py` - Exports submit_approved_decision and 2 more
- `market_view_assembler.py` - Exports build_alpha_snapshot and 3 more
- `market_rotation.py` - Exports _Health and 1 more
- `market_catalog.py` - Exports InstrumentTokenMeta and 2 more
- `live_node.py` - Exports assert_no_live_polymarket_execution and 10 more
- `instrument_markets.py` - Exports PolymarketInstrumentMarketBuilder
- `decision_policy.py` - Exports decision_policy_from_settings and 5 more
- `custom_data_types.py` - Exports is_polymarket_rtds_crypto_price and 11 more
- `custom_data_state.py` - Exports event_datetime and 4 more
- `custom_data_publisher.py` - Exports market_metadata and 3 more
- `cache_trading_state.py` - Exports cache_has_active_order_dedupe_key and 1 more
- `cache_market_data.py` - Exports NautilusCacheMarketDataProvider
- `backtest_node.py` - Exports build_backtest_engine
- `__init__.py` - Application code

🔄 **Self-reference**: When files in this folder change, update this index and PROJECT_INDEX.md
