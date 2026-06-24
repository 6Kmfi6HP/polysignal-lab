from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from polysignal_lab.strategies.config import (  # noqa: F401
    LateConsensusConfig,
    PTBDiffConfig,
    StrategyConfig,
    VWAPMomentumConfig,
)


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

DISALLOWED_SOURCE_SYMBOLS = tuple(
    [
        "Secure" + "Client",
        "Async" + "Secure" + "Client",
        "Clob" + "Client(",
        "create_" + "order",
        "post_" + "order",
        "submit_" + "order",
        "cancel_" + "order",
        "cancel_" + "all",
        "redeem_" + "positions",
    ]
)

YAML_CONFIG_ADAPTER: Final = TypeAdapter(dict[str, JsonValue])


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
    mode: Literal["signal_only", "paper_only", "signal_plus_paper"] = (
        "signal_plus_paper"
    )
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
        if (
            self.allow_secret_key_material
            or self.allow_secure_polymarket_client
            or self.allow_live_market_actions
            or self.allow_position_redemption
        ):
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
    publish_timeout_sec: float = 20.0
    dry_run: bool = True

    @property
    def resolved_bot_token(self) -> str | None:
        return os.environ.get(self.bot_token_env)

    @property
    def resolved_channel_id(self) -> str | None:
        return os.environ.get(self.channel_id_env)


class MarketConfig(BaseModel):
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP"])
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
    chain_id: int = 137
    market_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    use_market_ws: bool = True
    use_crypto_price_api: bool = False
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    use_rtds_ws: bool = True
    rtds_assets: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")
    rest_rate_limit_per_sec: float = 8.0
    max_book_staleness_ms: int = 60000  # 60s — books refetched every ~30-40s via REST
    max_market_metadata_staleness_ms: int = 10000


class BinanceDataConfig(BaseModel):
    enabled: bool = True
    base_ws_url: str = "wss://stream.binance.com:9443/stream"
    symbols: dict[str, str] = Field(
        default_factory=lambda: {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT",
            "SOL": "SOLUSDT",
            "XRP": "XRPUSDT",
        }
    )
    streams: list[str] = Field(default_factory=lambda: ["aggTrade", "bookTicker"])
    max_price_staleness_ms: int = (
        60000  # 60s — Binance WS updates every ~1s but allow initial lag
    )
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

    max_snapshot_concurrency: int = 4

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
            data = YAML_CONFIG_ADAPTER.validate_python(yaml.safe_load(fh) or {})
        # Apply env overrides (POLYSIGNAL_LAB__SECTION__KEY format)
        prefix = "POLYSIGNAL_LAB__"
        for env_key, env_val in _os.environ.items():
            if not env_key.startswith(prefix):
                continue
            parts = env_key[len(prefix) :].lower().split("__")
            target = data
            for part in parts[:-1]:
                section = target.get(part)
                if not isinstance(section, dict):
                    section = {}
                    target[part] = section
                target = section
            if not isinstance(target, dict):
                continue
            target[parts[-1]] = _yaml_bool(env_val)
        explicit_strategy_names: tuple[str, ...] = ()
        strategies_data = data.get("strategies")
        if isinstance(strategies_data, dict):
            explicit_strategy_names = tuple(strategies_data)
        settings = cls.model_validate(data)
        settings.strategies.set_explicit_strategy_names(explicit_strategy_names)
        settings.validate_runtime_environment()
        return settings

    def validate_runtime_environment(
        self, environ: dict[str, str] | None = None
    ) -> None:
        env = environ or os.environ
        if self.safety.fail_on_disallowed_env_keys:
            for key in env:
                upper = key.upper()
                if any(part in upper for part in DISALLOWED_ENV_KEY_PARTS):
                    raise SecurityConfigError(
                        f"Disallowed environment variable detected: {key}"
                    )


def load_settings(path: str | Path | None = None) -> Settings:
    if path is None:
        candidate = Path("config/signal_bot.yaml")
        return Settings.from_yaml(candidate) if candidate.exists() else Settings()
    return Settings.from_yaml(path)
