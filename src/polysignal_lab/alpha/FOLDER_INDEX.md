## 📁 alpha/

**Architecture**:
- Application code

**Files**:
- `legacy_snapshot_adapter.py` - Exports market_view_from_snapshot and decision_to_signal
- `vwap_trade_history.py` - Exports TradeHistory
- `vwap_state.py` - Exports encode_vwap_state, decode_vwap_state, restore_vwap_state_fields
- `vwap_momentum_core.py` - Exports VWAPMomentumAlphaCore
- `types.py` - Exports SideBookView and 13 more
- `state.py` - Exports json_safe_state and 1 more
- `skew_mean_reversion_core.py` - Exports SkewMeanReversionAlphaCore
- `ptb_diff_core.py` - Exports compute_tp_sl_thresholds and PTBDiffAlphaCore
- `pre_order_market_core.py` - Exports PreOrderMarketAlphaCore
- `one_cent_buy_core.py` - Exports OneCentBuyAlphaCore
- `ninety_nine_cent_sniper_core.py` - Exports NinetyNineCentSniperAlphaCore
- `mid_price_sizing_core.py` - Exports MidPriceSizingAlphaCore
- `low_side_dual_reversion_core.py` - Exports LowSideDualReversionAlphaCore
- `late_consensus_core.py` - Exports LateConsensusAlphaCore
- `helpers.py` - Shared alpha helpers including evaluate_from_snapshot_for_test
- `fibonacci_core.py` - Exports _RollingPriceStats and 3 more
- `dump_hedge_core.py` - Exports RollingPriceStats and 1 more
- `cross_market_core.py` - Exports RelationType and 2 more
- `binary_momentum_core.py` - Exports _RollingPriceStats and 1 more
- `__init__.py` - Application code

🔄 **Self-reference**: When files in this folder change, update this index and PROJECT_INDEX.md
