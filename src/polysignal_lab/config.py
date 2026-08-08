from __future__ import annotations

import os
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from polysignal_lab.domain.strategy_config import (  # noqa: F401
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
    timezone: str = "Asia/Bangkok"
    log_level: str = "INFO"


class LoggingConfig(BaseModel):
    """File logging for postmortems. `app.log_level` stays the stdout level.

    Both the Python logger and the Nautilus Rust logger write rotating JSONL
    into `directory`, so `docker logs` survives as the live human view while
    agents query the files with `jq`.
    """

    directory: str = "logs/runtime"
    # "OFF" disables file output entirely.
    file_level: str = "INFO"
    file_max_bytes: int = 50_000_000
    # Python and Nautilus each keep their own set, so this caps disk at
    # 2 x 50MB x (5 + 1) = 600MB.
    file_backup_count: int = 5
    # Containers have no TTY; ANSI codes only make the stream harder to parse.
    colors: bool = False
    # data_actor emitted 70% of all log lines (subscribe/unsubscribe commands),
    # pushing the failure window out of Docker's rotation before it was read.
    component_levels: dict[str, str] = Field(
        default_factory=lambda: {"nautilus_common::actor::data_actor": "WARN"}
    )


class SafetyConfig(BaseModel):
    allow_secret_key_material: bool = False
    allow_secure_polymarket_client: bool = False
    allow_live_market_actions: bool = False
    allow_position_redemption: bool = False
    fail_on_disallowed_env_keys: bool = True


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    channel_id_env: str = "TELEGRAM_CHANNEL_ID"
    parse_mode: str = "HTML"
    send_signals: bool = True
    send_consensus_signals: bool = True
    send_report_results: bool = True
    send_daily_report: bool = True
    send_health_alerts: bool = True
    max_message_chars: int = 4096
    retry_attempts: int = 3
    publish_timeout_sec: float = 20.0
    dry_run: bool = True
    interactive_enabled: bool = False
    interactive_dry_run: bool = False
    interactive_allowed_chat_ids: tuple[int, ...] = ()
    interactive_poll_interval_sec: float = 0.0
    interactive_poll_timeout_sec: int = 30
    interactive_drop_pending_updates_on_start: bool = True

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

    @field_validator("timeframes")
    @classmethod
    def normalize_timeframes(cls, value: list[str]) -> list[str]:
        normalized = [timeframe.strip().lower() for timeframe in value]
        if any(not timeframe for timeframe in normalized):
            raise ValueError("market timeframes must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("market timeframes contain duplicate client routes")
        return normalized


class PolymarketDataConfig(BaseModel):
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    chain_id: int = 137
    market_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    use_market_ws: bool = True
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    rest_rate_limit_per_sec: float = 8.0
    max_book_staleness_ms: int = 60000  # 60s — trade/core freshness gate
    # Readiness miss / recovery uses a wider window so quiet markets do not
    # immediately arm Docker liveness or per-minute wire refresh thrash.
    max_book_readiness_staleness_ms: int = 180000
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


class ExitModelConfig(BaseModel):
    mode: str = "hold_to_resolution_with_optional_tp_sl"
    take_profit_enabled: bool = True
    stop_loss_enabled: bool = True
    take_profit_price: float = 0.90
    stop_loss_price: float = 0.35
    max_hold_time_sec: int = 900


class TradingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starting_balance_usdc: float = 1000.0
    stake_mode: Literal["fixed"] = "fixed"
    fixed_stake_usdc: float = 10.0
    exit_model: ExitModelConfig = Field(default_factory=ExitModelConfig)


class StorageConfig(BaseModel):
    sqlite_enabled: bool = True
    sqlite_path: str = "data/polysignal_lab.sqlite3"
    jsonl_enabled: bool = True
    jsonl_dir: str = "logs"
    state_dir: str = "state"
    recorded_market_data_dir: str = "data/recorded_market_data"
    recorded_market_data_enabled: bool = True


class RetentionConfig(BaseModel):
    """Controls data retention for SQLite, JSONL, and runtime logs.

    Maintenance runs as a separate entrypoint command (no in-process timer).
    """

    enabled: bool = True
    archive_dir: str = "archive"
    sqlite_soft_limit_bytes: int = 900_000_000
    sqlite_hard_limit_bytes: int = 1_200_000_000
    sqlite_batch_rows: int = 5_000
    sqlite_hot_days: int = 14
    jsonl_max_file_bytes: int = 100_000_000
    jsonl_hot_days: int = 14
    jsonl_archive_days: int = 365
    runtime_log_soft_limit_bytes: int = 800_000_000
    runtime_log_hard_limit_bytes: int = 1_000_000_000
    crash_log_max_bytes: int = 25_000_000
    crash_log_max_days: int = 30


class DashboardConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    read_only: bool = True


class HealthLivenessConfig(BaseModel):
    heartbeat_max_age_sec: int = 120
    max_readiness_miss_sec: int = 300
    # Rotation resets per-condition readiness every cycle, so the window above
    # can never elapse while the runtime re-subscribes to nothing. This one
    # measures the last book update across all rotations and does not reset.
    # 0 disables the check.
    max_data_starvation_sec: int = 900


class HealthRestartGateConfig(BaseModel):
    enabled: bool = True
    critical_components: tuple[str, ...] = ("runtime", "sqlite")
    critical_down_sec: int = 300
    min_consecutive_failures: int = 5
    docker_healthcheck_fails_on_restart_recommended: bool = False


class HealthAlertConfig(BaseModel):
    """Push a Telegram alert when the runtime stays un-live.

    The runtime already reports startup, shutdown and signals, but said nothing
    while sitting unhealthy — the failure only reached the heartbeat file.
    Thresholds mirror the restart gate so a brief flap never pages anyone.
    """

    enabled: bool = True
    poll_interval_sec: int = 30
    # evaluate_liveness already absorbs the readiness tolerance window
    # (liveness.max_readiness_miss_sec), so this only has to outlast a
    # flapping healthcheck — not repeat that wait.
    min_unhealthy_sec: int = 60
    min_consecutive_failures: int = 3


class HealthConfig(BaseModel):
    startup_grace_sec: int = 180
    alert: HealthAlertConfig = Field(default_factory=HealthAlertConfig)
    liveness: HealthLivenessConfig = Field(default_factory=HealthLivenessConfig)
    restart_gate: HealthRestartGateConfig = Field(
        default_factory=HealthRestartGateConfig
    )


class NautilusSpotDataConfig(BaseModel):
    source: Literal["disabled", "polymarket_rtds"] = "disabled"


class NautilusDataClientConfig(BaseModel):
    ws_max_subscriptions_per_connection: int = 200


class NautilusMarketRotationConfig(BaseModel):
    enabled: bool = True
    interval_sec: int = Field(default=10, gt=0)
    include_next_periods: int = 1
    stale_grace_sec: int = 5
    unsubscribe_exited: bool = True


class NautilusBacktestConfig(BaseModel):
    data_dir: str = "data/nautilus_backtest"
    start: str | None = None
    end: str | None = None
    starting_balance_usdc: float = 1000.0


class NautilusRiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_order_submit_rate: str = "100/00:00:01"
    max_order_modify_rate: str = "100/00:00:01"
    max_notional_per_order: dict[str, str] = Field(default_factory=dict)


class NautilusRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trader_id: str = "PolySignal-Nautilus-001"
    python: str = "3.12"
    execution_mode: Literal["sandbox", "live", "backtest"] = "sandbox"
    sandbox_base_currency: str = "pUSD"
    sandbox_book_type: Literal["L1_MBP", "L2_MBP"] = "L2_MBP"
    l1_book_snapshot_interval_ms: int = 1000
    allow_live_polymarket_execution: bool = False
    backtest: NautilusBacktestConfig = Field(default_factory=NautilusBacktestConfig)
    risk: NautilusRiskConfig = Field(default_factory=NautilusRiskConfig)
    intercept_os_signals: bool = False
    polymarket_data: NautilusDataClientConfig = Field(
        default_factory=NautilusDataClientConfig
    )
    spot_data: NautilusSpotDataConfig = Field(default_factory=NautilusSpotDataConfig)
    market_rotation: NautilusMarketRotationConfig = Field(
        default_factory=NautilusMarketRotationConfig
    )

    @field_validator("sandbox_base_currency")
    @classmethod
    def validate_sandbox_base_currency(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("sandbox_base_currency must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_execution_mode(self) -> "NautilusRuntimeConfig":
        if self.execution_mode != "live" and self.allow_live_polymarket_execution:
            raise ValueError("live Polymarket execution is invalid outside live mode")
        if self.execution_mode == "live" and not self.allow_live_polymarket_execution:
            raise ValueError("live mode requires allow_live_polymarket_execution")
        return self


class RuntimeConfig(BaseModel):
    nautilus: NautilusRuntimeConfig = Field(default_factory=NautilusRuntimeConfig)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="forbid")

    app: AppConfig = Field(default_factory=AppConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    markets: MarketConfig = Field(default_factory=MarketConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

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
