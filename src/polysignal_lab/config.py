from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecurityConfigError(RuntimeError):
    pass


DISALLOWED_ENV_KEY_PARTS = (
    "PRIVATE_KEY",
    "MNEMONIC",
    "SEED_PHRASE",
    "WALLET_SECRET",
    "POLYMARKET_SECRET",
    "CLOB_SECRET",
    "TRADING_SECRET",
)

DISALLOWED_SOURCE_SYMBOLS = tuple([
    "Secure" + "Client",
    "Async" + "Secure" + "Client",
    "Clob" + "Client(",
    "create_" + "order",
    "post_" + "order",
    "submit_" + "order",
    "cancel_" + "order",
    "cancel_" + "all",
    "redeem_" + "positions",
])


def _yaml_bool(val: str) -> bool | str:
    """Convert env string to bool if it looks like one."""
    low = val.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return val


class AppConfig(BaseModel):
    name: str = "PolySignal Lab"
    environment: str = "production"
    mode: Literal["signal_only", "paper_only", "signal_plus_paper"] = "signal_plus_paper"
    timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"


class SafetyConfig(BaseModel):
    allow_secret_key_material: bool = False
    allow_secure_polymarket_client: bool = False
    allow_live_market_actions: bool = False
    allow_position_redemption: bool = False
    fail_on_disallowed_env_keys: bool = True

    @model_validator(mode="after")
    def validate_locked_down(self) -> "SafetyConfig":
        if self.allow_secret_key_material or self.allow_secure_polymarket_client or self.allow_live_market_actions or self.allow_position_redemption:
            raise ValueError("Safety flags must remain false for PolySignal Lab.")
        return self


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    channel_id_env: str = "TELEGRAM_CHANNEL_ID"
    parse_mode: str = "HTML"
    send_signals: bool = True
    send_consensus_signals: bool = True
    send_paper_results: bool = True
    send_daily_report: bool = True
    max_message_chars: int = 4096
    retry_attempts: int = 3
    dry_run: bool = True

    @property
    def resolved_bot_token(self) -> str | None:
        return os.environ.get(self.bot_token_env)

    @property
    def resolved_channel_id(self) -> str | None:
        return os.environ.get(self.channel_id_env)


class MarketConfig(BaseModel):
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    refresh_interval_sec: int = 10
    active_only: bool = True
    closed: bool = False
    cache_ttl_sec: int = 30

    @field_validator("assets")
    @classmethod
    def normalize_assets(cls, value: list[str]) -> list[str]:
        return [x.upper() for x in value]


class PolymarketDataConfig(BaseModel):
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    market_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    use_market_ws: bool = True
    rest_rate_limit_per_sec: float = 8.0
    max_book_staleness_ms: int = 60000  # 60s — books refetched every ~30-40s via REST
    max_market_metadata_staleness_ms: int = 10000


class BinanceDataConfig(BaseModel):
    enabled: bool = True
    base_ws_url: str = "wss://stream.binance.com:9443/stream"
    symbols: dict[str, str] = Field(default_factory=lambda: {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "BNB": "BNBUSDT",
    })
    streams: list[str] = Field(default_factory=lambda: ["aggTrade", "bookTicker"])
    max_price_staleness_ms: int = 60000  # 60s — Binance WS updates every ~1s but allow initial lag
    reconnect_before_hours: int = 23


class DataConfig(BaseModel):
    polymarket: PolymarketDataConfig = Field(default_factory=PolymarketDataConfig)
    binance: BinanceDataConfig = Field(default_factory=BinanceDataConfig)


class SignalConfig(BaseModel):
    min_confidence_to_publish: float = 0.50
    dedupe_enabled: bool = True
    dedupe_ttl_sec: int = 300
    consensus_enabled: bool = True
    consensus_window_sec: int = 45
    max_signals_per_market: int = 3
    max_signals_per_hour: int = 60


class FillModelConfig(BaseModel):
    type: str = "best_ask_taker"
    slippage_bps: float = 25.0
    require_depth_check: bool = True
    min_fill_ratio: float = 1.0
    reject_if_partial: bool = True
    max_fill_delay_ms: int = 1000


class ExitModelConfig(BaseModel):
    mode: str = "hold_to_resolution_with_optional_tp_sl"
    take_profit_enabled: bool = True
    stop_loss_enabled: bool = True
    take_profit_price: float = 0.90
    stop_loss_price: float = 0.35
    max_hold_time_sec: int = 900


class PaperTradingConfig(BaseModel):
    enabled: bool = True
    starting_balance_usdc: float = 1000.0
    stake_mode: Literal["fixed"] = "fixed"
    fixed_stake_usdc: float = 10.0
    max_open_positions: int = 10
    max_market_exposure_usdc: float = 30.0
    max_strategy_exposure_usdc: float = 100.0
    fill_model: FillModelConfig = Field(default_factory=FillModelConfig)
    exit_model: ExitModelConfig = Field(default_factory=ExitModelConfig)


class StorageConfig(BaseModel):
    sqlite_enabled: bool = True
    sqlite_path: str = "data/polysignal_lab.sqlite3"
    jsonl_enabled: bool = True
    jsonl_dir: str = "logs"
    state_dir: str = "state"


class DashboardConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    read_only: bool = True


class VWAPMomentumConfig(BaseModel):
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    min_price: float = 0.35
    max_price: float = 0.85
    # Time-based windows (replaces old count-based window_size)
    vwap_window_sec: int = 30
    momentum_window_sec: int = 60
    # Deviation limits (percentages: 3.0 = 3.0%)
    min_deviation_pct: float = 3.0
    max_deviation_pct: float = 100.0
    # Entry window
    min_elapsed_sec: int = 150
    no_entry_before_end_sec: int = 90
    # Momentum threshold (%): signals require momentum > this value to avoid noise
    min_momentum_pct: float = 5.0


class LateConsensusConfig(BaseModel):
    """Meridian Late Entry V3 configuration.

    Implements the 8-step Late Entry V3 strategy from PolyBullLabs.
    """
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])

    # -- Step 1: Entry window (seconds before close) --
    entry_window_sec: int = 240

    # -- Step 2: Entry frequency (minimum seconds between entries per market) --
    entry_frequency_sec: int = 7

    # -- Step 3: Spread = ask_sum (up_ask + down_ask) must be <= this --
    max_ask_sum: float = 1.05

    # -- Step 4: Confidence = |up_ask - down_ask| --
    min_confidence_abs: float = 0.30

    # -- Step 6: Price ceiling --
    max_entry_price: float = 0.92

    # -- Step 7: Max investment per market (enforced by paper wallet layer) --
    max_investment_per_market: float = 300.0

    # -- Step 8: Dynamic position sizing (contracts) --
    sizing_above_180: int = 8
    sizing_above_120: int = 10
    sizing_below_120: int = 12

    # -- Flip guard (prevent side flips within window) --
    flip_guard_enabled: bool = True
    flip_guard_window_sec: int = 20

    # -- Flip stop (exit when price drops below threshold) --
    flip_stop_enabled: bool = True
    flip_stop_price: float = 0.48

    # -- Per-coin stop loss config --
    stop_loss_per_coin: dict[str, dict] = Field(default_factory=lambda: {
        "BTC": {"type": "fixed", "value": -12.0},
        "ETH": {"type": "fixed", "value": -12.0},
        "SOL": {"type": "fixed", "value": -12.0},
        "XRP": {"type": "fixed", "value": -11.0},
    })

    # Kept for backward compatibility (no longer used by strategy logic)
    min_confidence: float | None = None
    max_spread: float | None = None


class PTBConditionConfig(BaseModel):
    """一组 PTB 触发条件 (C1-C4)"""
    name: str  # e.g. "C1", "C2", "C3", "C4"
    side: str  # "UP" or "DOWN"
    time_sec: int  # 允许的最大剩余秒数
    min_diff_usd: float  # 最小差价 USD
    min_prob: float  # 最小买入概率
    max_prob: float  # 最大买入概率


class PTBExitConfig(BaseModel):
    """概率空间 TP/SL 退出配置"""
    stop_loss_prob_pct: float = 0.20  # 止损比例 (entry_prob 的百分比下跌)
    take_profit_rr: float = 3.0  # 风险回报比
    take_profit_cap: float = 0.95  # 最大止盈概率
    market_data_max_lag_sec: int = 2  # 数据最大延迟秒数


class PTBDiffConfig(BaseModel):
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    require_verified_ptb_source: bool = True
    conditions: list[PTBConditionConfig] = Field(default_factory=lambda: [
        PTBConditionConfig(name="C1", side="UP", time_sec=120, min_diff_usd=30, min_prob=0.80, max_prob=0.92),
        PTBConditionConfig(name="C2", side="DOWN", time_sec=120, min_diff_usd=30, min_prob=0.80, max_prob=0.92),
        PTBConditionConfig(name="C3", side="UP", time_sec=60, min_diff_usd=50, min_prob=0.80, max_prob=0.92),
        PTBConditionConfig(name="C4", side="DOWN", time_sec=60, min_diff_usd=50, min_prob=0.80, max_prob=0.92),
    ])
    exit_config: PTBExitConfig = Field(default_factory=PTBExitConfig)


class SkewMeanReversionConfig(BaseModel):
    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])
    min_skew_ratio: float = 0.015  # 1.5% — typical dev is ~1.98% (0.51 vs 0.50)
    max_skew_ratio: float = 0.10
    min_confidence: float = 0.50
    base_confidence: float = 0.55
    max_confidence: float = 0.90
    max_entry_price: float = 0.85
    max_spread: float = 0.10
    max_seconds_to_close: int = 86400  # 24h — works across full lifecycle


class StrategyConfig(BaseModel):
    vwap_momentum: VWAPMomentumConfig = Field(default_factory=VWAPMomentumConfig)
    late_consensus: LateConsensusConfig = Field(default_factory=LateConsensusConfig)
    ptb_diff: PTBDiffConfig = Field(default_factory=PTBDiffConfig)
    skew_mean_reversion: SkewMeanReversionConfig = Field(default_factory=SkewMeanReversionConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    app: AppConfig = Field(default_factory=AppConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    markets: MarketConfig = Field(default_factory=MarketConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    paper_trading: PaperTradingConfig = Field(default_factory=PaperTradingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        import os as _os
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        # Apply env overrides (POLYSIGNAL_LAB__SECTION__KEY format)
        prefix = "POLYSIGNAL_LAB__"
        for env_key, env_val in _os.environ.items():
            if not env_key.startswith(prefix):
                continue
            parts = env_key[len(prefix):].lower().split("__")
            target = data
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]
            if not isinstance(target, dict):
                continue
            target[parts[-1]] = _yaml_bool(env_val)
        settings = cls.model_validate(data)
        settings.validate_runtime_environment()
        return settings

    def validate_runtime_environment(self, environ: dict[str, str] | None = None) -> None:
        env = environ or os.environ
        if self.safety.fail_on_disallowed_env_keys:
            for key in env:
                upper = key.upper()
                if any(part in upper for part in DISALLOWED_ENV_KEY_PARTS):
                    raise SecurityConfigError(f"Disallowed environment variable detected: {key}")


def load_settings(path: str | Path | None = None) -> Settings:
    if path is None:
        candidate = Path("config/signal_bot.yaml")
        return Settings.from_yaml(candidate) if candidate.exists() else Settings()
    return Settings.from_yaml(path)
