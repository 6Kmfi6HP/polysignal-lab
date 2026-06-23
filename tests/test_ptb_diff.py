from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, assert_never

from pydantic import ValidationError

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.strategies.config import PTBDiffConfig, PTBTriggerConfig
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.utils import stable_hash, utc_now
from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market


PRICE_TO_BEAT: Final = 100_000.0


@dataclass(frozen=True, slots=True)
class PtbScenario:
    side: Side = Side.UP
    diff_usd: float = 100.0
    side_ask: float = 0.70
    opposing_ask: float = 0.25
    seconds_to_close: int | None = 120
    asset: str = "BTC"
    timeframe: str = "5m"
    verified_ptb: bool = True
    has_spot: bool = True
    has_price_to_beat: bool = True
    has_side_book: bool = True
    side_spread: float = 0.02
    staleness_ms: int = 0


def _config() -> PTBDiffConfig:
    return PTBDiffConfig(
        max_spread=0.08,
        triggers=[
            PTBTriggerConfig(
                name="strong_up_late",
                side=Side.UP,
                min_diff_usd=80.0,
                max_token_price=0.78,
                min_probability_edge=0.08,
                min_seconds_to_close=30,
                max_seconds_to_close=180,
            ),
            PTBTriggerConfig(
                name="strong_down_late",
                side=Side.DOWN,
                min_diff_usd=80.0,
                max_token_price=0.78,
                min_probability_edge=0.08,
                min_seconds_to_close=30,
                max_seconds_to_close=180,
            ),
        ],
    )


def _snapshot(scenario: PtbScenario) -> MarketSnapshot:
    created_at = utc_now()
    end_ts = None if scenario.seconds_to_close is None else created_at + timedelta(seconds=scenario.seconds_to_close)
    price_to_beat = PRICE_TO_BEAT if scenario.has_price_to_beat else None
    market = sample_market(
        MarketFactoryConfig(
            asset=scenario.asset,
            timeframe=scenario.timeframe,
            seconds_to_close=scenario.seconds_to_close or 120,
            price_to_beat=PRICE_TO_BEAT,
        )
    ).model_copy(update={"end_ts": end_ts, "price_to_beat": price_to_beat})
    book_received_at = created_at - timedelta(milliseconds=scenario.staleness_ms)
    match scenario.side:
        case Side.UP:
            up_ask = scenario.side_ask
            down_ask = scenario.opposing_ask
        case Side.DOWN:
            up_ask = scenario.opposing_ask
            down_ask = scenario.side_ask
        case unreachable:
            assert_never(unreachable)
    up_book = sample_book(
        market.token_for(Side.UP).token_id,
        BookFactoryConfig(ask=up_ask, bid=up_ask - scenario.side_spread, size=500.0),
    ).model_copy(update={"received_at": book_received_at})
    down_book = sample_book(
        market.token_for(Side.DOWN).token_id,
        BookFactoryConfig(ask=down_ask, bid=down_ask - scenario.side_spread, size=500.0),
    ).model_copy(update={"received_at": book_received_at})
    if not scenario.has_side_book:
        match scenario.side:
            case Side.UP:
                up_book = None
            case Side.DOWN:
                down_book = None
            case unreachable:
                assert_never(unreachable)
    spot = None
    if scenario.has_spot:
        spot = SpotPrice(
            asset=scenario.asset,
            symbol=f"{scenario.asset}USDT",
            price=PRICE_TO_BEAT + scenario.diff_usd,
            received_at=book_received_at,
            event_time=book_received_at,
        )
    return MarketSnapshot(
        snapshot_id=f"snap_{stable_hash(scenario.asset, scenario.side.value, str(scenario.diff_usd))}",
        created_at=created_at,
        market=market,
        up_book=up_book,
        down_book=down_book,
        spot=spot,
        price_to_beat=price_to_beat,
        freshness=FreshnessState(
            up_book_ms=scenario.staleness_ms,
            down_book_ms=scenario.staleness_ms,
            spot_ms=scenario.staleness_ms if scenario.has_spot else None,
            max_ms=scenario.staleness_ms,
        ),
        metrics={"price_to_beat_verified": scenario.verified_ptb},
    )


def test_ptb_diff_emits_buy_up_and_down_from_trigger_rows() -> None:
    # Given: PRD trigger rows for the BTC 5m PTB strategy.
    strategy = PTBDiffStrategy(_config())

    # When: spot is above and below PTB with token ask below the configured max.
    up_signal = strategy.evaluate(_snapshot(PtbScenario(side=Side.UP, diff_usd=100.0, side_ask=0.70)))[0]
    down_signal = strategy.evaluate(_snapshot(PtbScenario(side=Side.DOWN, diff_usd=-100.0, side_ask=0.70)))[0]

    # Then: BUY_UP and BUY_DOWN candidates carry concrete PRD reasons and metrics.
    assert up_signal.side == Side.UP
    assert down_signal.side == Side.DOWN
    assert "PTB_SPOT_ABOVE_PTB" in up_signal.reason_codes
    assert "PTB_SPOT_BELOW_PTB" in down_signal.reason_codes
    assert "PTB_PROBABILITY_EDGE_OK" in up_signal.reason_codes
    assert up_signal.metrics["trigger"] == "strong_up_late"
    assert down_signal.metrics["trigger"] == "strong_down_late"
    assert up_signal.metrics["token_ask"] == 0.70
    assert up_signal.metrics["directional_probability"] == 1.0
    assert round(up_signal.metrics["probability_edge"], 2) == 0.30
    assert up_signal.metrics["max_token_price"] == 0.78
    assert up_signal.max_entry_price == 0.78


def test_ptb_diff_rejects_above_max_token_price() -> None:
    # Given: a valid UP scenario except the token ask exceeds the trigger ceiling.
    strategy = PTBDiffStrategy(_config())

    # When: the side ask is above max_token_price.
    signals = strategy.evaluate(_snapshot(PtbScenario(side=Side.UP, diff_usd=100.0, side_ask=0.79)))

    # Then: no candidate is emitted.
    assert signals == []


def test_ptb_diff_rejects_below_probability_edge() -> None:
    # Given: token price is allowed, but implied edge is below the trigger minimum.
    config = _config().model_copy(
        update={
            "triggers": [
                PTBTriggerConfig(
                    name="strong_up_late",
                    side=Side.UP,
                    min_diff_usd=80.0,
                    max_token_price=0.99,
                    min_probability_edge=0.08,
                    min_seconds_to_close=30,
                    max_seconds_to_close=180,
                )
            ]
        }
    )
    strategy = PTBDiffStrategy(config)

    # When: the side ask leaves only 0.07 probability edge.
    signals = strategy.evaluate(_snapshot(PtbScenario(side=Side.UP, diff_usd=100.0, side_ask=0.93)))

    # Then: no candidate is emitted below min_probability_edge.
    assert signals == []


def test_ptb_diff_rejects_below_diff_threshold_and_wrong_direction() -> None:
    # Given: PRD trigger rows with an 80 USD minimum directional diff.
    config = _config().model_copy(update={"triggers": [_config().triggers[0]]})
    strategy = PTBDiffStrategy(config)

    # When: movement is too small or points against the trigger side.
    low_diff = strategy.evaluate(_snapshot(PtbScenario(side=Side.UP, diff_usd=79.0, side_ask=0.70)))
    wrong_direction = strategy.evaluate(_snapshot(PtbScenario(side=Side.UP, diff_usd=-100.0, side_ask=0.70)))

    # Then: both diff failures reject safely.
    assert low_diff == []
    assert wrong_direction == []


def test_ptb_diff_rejects_outside_time_window() -> None:
    # Given: PRD trigger rows limited to 30-180 seconds before close.
    strategy = PTBDiffStrategy(_config())

    # When: the market is too close to close or too early.
    too_close = strategy.evaluate(_snapshot(PtbScenario(seconds_to_close=29)))
    too_early = strategy.evaluate(_snapshot(PtbScenario(seconds_to_close=181)))

    # Then: both time-window violations reject safely.
    assert too_close == []
    assert too_early == []


def test_ptb_diff_rejects_malformed_or_unsupported_inputs() -> None:
    # Given: malformed PTB snapshots that lack required PRD inputs.
    strategy = PTBDiffStrategy(_config())

    # When: each malformed or unsupported input is evaluated.
    cases = [
        PtbScenario(has_price_to_beat=False),
        PtbScenario(has_spot=False),
        PtbScenario(has_side_book=False),
        PtbScenario(verified_ptb=False),
        PtbScenario(asset="ETH"),
        PtbScenario(timeframe="1h"),
        PtbScenario(seconds_to_close=None),
        PtbScenario(side_spread=0.09),
    ]

    # Then: every malformed input rejects without emitting a candidate.
    assert [strategy.evaluate(_snapshot(case)) for case in cases] == [[], [], [], [], [], [], [], []]


def test_ptb_diff_emits_stale_raw_data_candidate_for_signal_gate() -> None:
    # Given: a PTB snapshot whose raw market data exceeds PTB freshness policy.
    strategy = PTBDiffStrategy(_config())

    # When: the strategy evaluates otherwise valid stale raw inputs.
    signals = strategy.evaluate(_snapshot(PtbScenario(staleness_ms=3_000)))

    # Then: PTB still emits a candidate for the central SignalGate freshness rejection.
    assert len(signals) == 1
    signal = signals[0]
    assert signal.freshness_policy is not None
    assert signal.freshness_policy.max_orderbook_staleness_ms == 1_000
    assert signal.freshness_policy.max_spot_staleness_ms == 1_000
    assert signal.data_freshness_ms == 3_000
    metrics = signal.metrics
    assert isinstance(metrics["orderbook_freshness_ms"], int | float)
    assert isinstance(metrics["spot_freshness_ms"], int | float)
    assert isinstance(metrics["max_lag_ms"], int | float)
    assert metrics["orderbook_freshness_ms"] == 3_000
    assert metrics["spot_freshness_ms"] == 3_000
    assert metrics["max_lag_ms"] == 1_000
    assert "PTB_ORDERBOOK_FRESH" not in signal.reason_codes


def test_ptb_diff_schema_rejects_old_probability_band_keys() -> None:
    # Given: the old runtime condition shape with min_prob/max_prob.
    old_row = {
        "name": "C1",
        "side": "UP",
        "time_sec": 120,
        "min_diff_usd": 30.0,
        "min_prob": 0.80,
        "max_prob": 0.92,
    }

    # When / Then: the PRD trigger schema rejects the stale row shape.
    try:
        PTBTriggerConfig.model_validate(old_row)
    except ValidationError:
        return
    raise AssertionError("old PTB probability-band row unexpectedly validated")
