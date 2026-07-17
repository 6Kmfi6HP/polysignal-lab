"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Iterable, collections.abc.Iterator, collections.abc.Mapping, enum, enum.StrEnum, typing, typing.Literal
Output: StrategyExecutionConfig, VWAPMomentumConfig, FixedStopLossConfig, StopLossPerCoinConfig, LateConsensusConfig, PTBTriggerConfig, PTBExitConfig, PTBDiffConfig, BinaryMomentumConfig, CrossMarketBotConfig
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, RootModel

from polysignal_lab.domain.enums import Side

class StrategyExecutionConfig(BaseModel):
    priority: int = 100
    depends_on: list[str] = Field(default_factory=list)
    execution_mode: Literal["stateless", "stateful", "cross_market"] = "stateful"



# ═══════════════════════════════════════════════════════════════════════
# Existing core strategy configs
# ═══════════════════════════════════════════════════════════════════════


class VWAPMomentumConfig(BaseModel):
    name: Literal["vwap_momentum"] = "vwap_momentum"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    min_price: float = 0.35
    max_price: float = 0.85
    vwap_window_sec: int = 30
    momentum_window_sec: int = 120
    min_deviation_pct: float = 0.015
    max_deviation_pct: float = 0.05
    min_momentum: float = 0.05
    min_z_score: float = 1.2
    min_elapsed_sec: int = 45
    no_entry_before_end_sec: int = 20
    max_spread: float = 0.03
    max_orderbook_staleness_ms: int = 60_000
    max_spot_staleness_ms: int = 60_000
    hedge_enabled: bool = False
    hedge_price: float = 0.02
    hedge_expiry_seconds: int = 3600


class FixedStopLossConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["fixed"] = "fixed"
    value: float


class StopLossPerCoinConfig(RootModel[Mapping[str, FixedStopLossConfig]]):
    model_config = ConfigDict(frozen=True)


class LateConsensusConfig(BaseModel):
    name: Literal["late_consensus"] = "late_consensus"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    entry_window_sec: int = 240
    entry_frequency_sec: int = 7
    max_ask_sum: float = 1.05
    min_confidence_abs: float = 0.30
    max_spread: float = 0.08
    max_orderbook_staleness_ms: int = 1_500
    max_spot_staleness_ms: int = 1_500
    min_spot_move_abs: float = 0.0
    max_entry_price: float = 0.93
    max_investment_per_market: float = 300.0
    sizing_above_180: int = 8
    sizing_above_120: int = 10
    sizing_below_120: int = 12
    flip_guard_enabled: bool = True
    flip_guard_window_sec: int = 20
    flip_stop_enabled: bool = True
    flip_stop_price: float = 0.48
    stop_loss_per_coin: StopLossPerCoinConfig = Field(
        default_factory=lambda: StopLossPerCoinConfig(
            {
                "BTC": FixedStopLossConfig(value=-12.0),
                "ETH": FixedStopLossConfig(value=-12.0),
                "SOL": FixedStopLossConfig(value=-12.0),
                "XRP": FixedStopLossConfig(value=-11.0),
            }
        )
    )
    min_confidence: float | None = None


class PTBTriggerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    side: Side
    min_diff_usd: float
    max_token_price: float
    min_token_price: float = 0.0
    min_probability_edge: float = 0.0
    min_seconds_to_close: int
    max_seconds_to_close: int


class PTBExitConfig(BaseModel):
    stop_loss_prob_pct: float = 0.15
    take_profit_rr: float = 1.0
    take_profit_cap: float = 0.99
    market_data_max_lag_sec: float = 1.0


class PTBDiffConfig(BaseModel):
    name: Literal["ptb_diff"] = "ptb_diff"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    require_verified_ptb_source: bool = True
    require_anchor_price_source: bool = False
    require_chainlink_spot_source: bool = True
    chainlink_spot_sources: tuple[str, ...] = ("polymarket_rtds", "chainlink", "chainlink_rtds")
    max_spread: float = 0.08
    triggers: list[PTBTriggerConfig] = Field(
        default_factory=lambda: [
            PTBTriggerConfig(
                name="r1_up",
                side=Side.UP,
                min_diff_usd=30.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            ),
            PTBTriggerConfig(
                name="r2_down",
                side=Side.DOWN,
                min_diff_usd=30.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            ),
            PTBTriggerConfig(
                name="r3_up",
                side=Side.UP,
                min_diff_usd=50.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=60,
            ),
            PTBTriggerConfig(
                name="r4_down",
                side=Side.DOWN,
                min_diff_usd=50.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=60,
            ),
        ]
    )
    exit_config: PTBExitConfig = Field(default_factory=PTBExitConfig)


# ═══════════════════════════════════════════════════════════════════════
# Restored strategy configs
# ═══════════════════════════════════════════════════════════════════════


class BinaryMomentumConfig(BaseModel):
    name: Literal["binary_momentum"] = "binary_momentum"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    rsi_upper: int = 75
    rsi_lower: int = 25
    rsi_up_min: int = 50
    rsi_down_max: int = 50
    vwap_deviation: float = 0.002
    max_token_price: float = 0.70
    max_notional: float = 25.0
    stop_loss_pct: float = 0.20
    take_profit_pct: float = 0.25


class CrossMarketBotConfig(BaseModel):
    name: Literal["cross_market_bot"] = "cross_market_bot"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(
        default_factory=lambda: StrategyExecutionConfig(execution_mode="cross_market")
    )
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    min_edge: float = 0.01
    max_leg_timeout_seconds: float = 1.5
    max_basket_notional: float = 50.0
    min_depth_shares: int = 5
    fee_rate: float = 0.01


class DumpHedgeConfig(BaseModel):
    name: Literal["dump_hedge"] = "dump_hedge"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    move_threshold: float = 0.15
    lookback_seconds: float = 30.0
    detection_window_minutes: float = 5.0
    leg_shares: int = 10
    pair_cost_cap: float = 0.95
    stop_loss_max_wait_seconds: float = 90.0
    stop_loss_pair_cap: float = 1.05


class FibonacciBotConfig(BaseModel):
    name: Literal["fibonacci_bot"] = "fibonacci_bot"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    zigzag_pct: float = 0.005
    zone_width_pct: float = 0.001
    ratios: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)
    extension_ratios: tuple[float, ...] = (1.0, 1.272, 1.618)
    fib_size_weights: tuple[int, ...] = (1, 1, 2, 3, 5)
    max_token_price: float = 0.6
    max_notional: float = 25.0
    require_momentum_confirmation: bool = True
    momentum_window: int = 8
    min_momentum_zscore: float = 1.0
    offset_from_fib: float = 0.02


class LowSideDualReversionConfig(BaseModel):
    name: Literal["low_side_dual_reversion"] = "low_side_dual_reversion"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    bid_prices: tuple[float, ...] = (0.35, 0.40, 0.45)
    shares_per_level: int = 5
    pair_cost_cap: float = 0.98
    max_unhedged_seconds: float = 20.0
    stop_loss_hedge_cap: float = 1.03
    cancel_before_close_seconds: float = 15.0
    fee_rate: float = 0.01
    slippage_buffer: float = 0.01


class SizingMode(StrEnum):
    MARTINGALE = "martingale"
    ANTI_MARTINGALE = "anti_martingale"


class MidPriceSizingConfig(BaseModel):
    name: Literal["mid_price_sizing"] = "mid_price_sizing"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    mode: SizingMode = SizingMode.MARTINGALE
    entry_center: float = 0.45
    entry_band: float = 0.05
    base_notional: float = 5.0
    adverse_step: float = 0.05
    favorable_step: float = 0.05
    max_layers: int = 3
    martingale_multiplier: float = 1.0
    anti_martingale_multiplier: float = 1.5
    min_signal_probability_edge: float = 0.03
    max_price: float = 0.6
    stop_price: float = 0.3
    take_profit_price: float = 0.7


class NinetyNineCentSniperConfig(BaseModel):
    name: Literal["ninety_nine_cent_sniper"] = "ninety_nine_cent_sniper"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    max_entry_price: float = 0.99
    min_external_probability: float = 0.995
    min_seconds_before_close: float = 0.0
    max_seconds_before_close: float = 90.0
    max_notional_per_trade: float = 25.0
    stop_price: float = 0.94
    require_effectively_settled: bool = True


class OneCentBuyConfig(BaseModel):
    name: Literal["one_cent_buy"] = "one_cent_buy"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    entry_prices: tuple[float, ...] = (0.01, 0.02, 0.03)
    shares_per_level: int = 10
    cancel_before_close_seconds: float = 20.0
    min_seconds_after_open: float = 0.0
    max_seconds_after_open: float = 280.0
    take_profit_ladder: list[tuple[float, float]] = Field(
        default_factory=lambda: [(0.10, 0.50), (0.15, 1.0)]
    )


class PreOrderMarketConfig(BaseModel):
    name: Literal["pre_order_market"] = "pre_order_market"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    seconds_before_open: float = 180.0
    seconds_after_open_expiry: float = 30.0
    ladder: list[tuple[float, int]] = Field(
        default_factory=lambda: [(0.45, 5), (0.40, 5)]
    )
    pair_cost_cap: float = 0.98
    reconcile_max_pair_cost: float = 1.00


class SkewMeanReversionConfig(BaseModel):
    name: Literal["skew_mean_reversion"] = "skew_mean_reversion"
    enabled: bool = True
    execution: StrategyExecutionConfig = Field(default_factory=StrategyExecutionConfig)
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    max_seconds_to_close: int = 3600
    min_skew_ratio: float = 0.05
    max_entry_price: float = 0.85
    max_spread: float = 0.05
    base_confidence: float = 0.55
    max_confidence: float = 0.90
    min_confidence: float = 0.40
    max_skew_ratio: float = 0.50


# ═══════════════════════════════════════════════════════════════════════
# Master strategy config — superset of all strategy configs
# ═══════════════════════════════════════════════════════════════════════


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vwap_momentum: VWAPMomentumConfig = Field(default_factory=VWAPMomentumConfig)
    late_consensus: LateConsensusConfig = Field(default_factory=LateConsensusConfig)
    ptb_diff: PTBDiffConfig = Field(default_factory=PTBDiffConfig)
    binary_momentum: BinaryMomentumConfig = Field(default_factory=BinaryMomentumConfig)
    cross_market_bot: CrossMarketBotConfig = Field(default_factory=CrossMarketBotConfig)
    dump_hedge: DumpHedgeConfig = Field(default_factory=DumpHedgeConfig)
    fibonacci_bot: FibonacciBotConfig = Field(default_factory=FibonacciBotConfig)
    low_side_dual_reversion: LowSideDualReversionConfig = Field(
        default_factory=LowSideDualReversionConfig
    )
    mid_price_sizing: MidPriceSizingConfig = Field(default_factory=MidPriceSizingConfig)
    ninety_nine_cent_sniper: NinetyNineCentSniperConfig = Field(
        default_factory=NinetyNineCentSniperConfig
    )
    one_cent_buy: OneCentBuyConfig = Field(default_factory=OneCentBuyConfig)
    pre_order_market: PreOrderMarketConfig = Field(default_factory=PreOrderMarketConfig)
    skew_mean_reversion: SkewMeanReversionConfig = Field(
        default_factory=SkewMeanReversionConfig
    )


    _explicit_strategy_names: tuple[str, ...] = PrivateAttr(default=())

    def set_explicit_strategy_names(self, names: Iterable[str]) -> None:
        self._explicit_strategy_names = tuple(names)

    def explicit_strategy_names(self) -> tuple[str, ...]:
        return self._explicit_strategy_names

    def __iter__(self) -> Iterator[BaseModel]:
        for name in self._explicit_strategy_names:
            yield getattr(self, name)
