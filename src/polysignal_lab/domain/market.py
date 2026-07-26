from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, JsonValue, computed_field

from polysignal_lab.domain.enums import MarketStatus, Side

JsonObject = dict[str, JsonValue]


class OutcomeToken(BaseModel):
    token_id: str
    side: Side
    outcome_name: str
    market_id: str


class Market(BaseModel):
    schema_version: int = 1
    market_id: str
    market_slug: str
    condition_id: str
    question_id: str | None = None
    question: str | None = None
    asset: str
    timeframe: str
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    status: MarketStatus = MarketStatus.UNKNOWN
    resolution_source: str | None = None
    price_to_beat: float | None = None
    resolved_outcome: Side | None = None
    outcome_tokens: list[OutcomeToken] = Field(default_factory=list)
    raw: JsonObject = Field(default_factory=dict)

    @computed_field
    @property
    def is_active(self) -> bool:
        return self.status == MarketStatus.ACTIVE

    def token_for(self, side: Side) -> OutcomeToken:
        for token in self.outcome_tokens:
            if token.side == side:
                return token
        raise KeyError(f"No token configured for {side} in {self.market_slug}")

    @classmethod
    def from_gamma(cls, payload: JsonObject, asset: str, timeframe: str) -> "Market":
        """Delegate Gamma parse to data/provider (NT adapter lives there)."""
        from polysignal_lab.data.provider.gamma_market import market_from_gamma

        return market_from_gamma(payload, asset, timeframe)
