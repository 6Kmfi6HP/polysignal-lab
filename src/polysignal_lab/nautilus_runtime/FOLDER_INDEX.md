## 📁 nautilus_runtime/

**Architecture**:
- Application code

**Files**:
- `strategy_builder.py` - Exports build_control and 1 more
- `state.py` - Application code
- `signal_sidecar.py` - Exports _PublishResultLike and 2 more
- `sidecar_data.py` - Exports market_metadata and 3 more
- `runtime_context_factory.py` - Exports NautilusRuntimeContext and build_nautilus_runtime_context
- `projections.py` - Projects native order, fill, position, account, and portfolio reporting payloads
- `order_plan.py` - Exports build_order_spec and 11 more
- `order_mapping.py` - Exports order_spec_from_decision
- `observability.py` - Records runtime lifecycle and diagnostic events
- `observability_persistence.py` - Routes durable lifecycle projections separately from best-effort telemetry
- `node_signals.py` - Application code
- `node_probes.py` - Application code
- `node_crash.py` - Application code
- `node_cli.py` - Exports run_nautilus_cli_async
- `node_builder.py` - Exports build_nautilus_runtime_context and 10 more
- `node.py` - Exports run_nautilus_cli and 1 more
- `native_strategy.py` - Exports PolySignalNativeStrategy
- `native_order.py` - Exports submit_approved_decision and 2 more
- `market_rotation.py` - Exports _MarketUniverse and 2 more
- `market_discovery_worker.py` - Exports MarketDiscoveryWorker
- `optional_imports.py` - Exports load_live_runtime_symbols and optional Nautilus import gateway
- `live_node.py` - Exports assert_no_live_polymarket_execution and 7 more
- `group_views.py` - Exports MarketGroupViewAssembler
- `decision_policy_actor.py` - Exports NautilusDecisionPolicyActor
- `decision_policy.py` - Exports ApprovedDecision and 6 more
- `custom_data_state.py` - Exports PriceToBeatView and 3 more
- `cache_reader.py` - Exports NautilusCacheReader
- `cache_market_data.py` - Exports NautilusCacheMarketDataProvider
- `__init__.py` - Application code

🔄 **Self-reference**: When files in this folder change, update this index and PROJECT_INDEX.md
