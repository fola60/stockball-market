from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID

from app.clients.trading_engine import OrderExecutionRecord, OrderSide


class StrategyEngine(StrEnum):
    NOISE = "NOISE"
    MARKET_MOMENTUM = "MARKET_MOMENTUM"
    STATS_VALUE = "STATS_VALUE"
    SOCIAL_SENTIMENT = "SOCIAL_SENTIMENT"
    PORTFOLIO_REBALANCER = "PORTFOLIO_REBALANCER"
    BETTING_MARKET_VALUE = "BETTING_MARKET_VALUE"


class BotStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class SpawnNameStyle(StrEnum):
    PERSONA = "PERSONA"
    NUMBERED = "NUMBERED"


class DecisionSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TickOutcomeStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SyntheticTraderBotConfigRecord:
    id: UUID
    config_key: str
    display_name: str
    strategy_engine: StrategyEngine
    version: int
    config: Mapping[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SyntheticTraderBotRecord:
    id: UUID
    account_id: UUID
    portfolio_id: UUID
    config_id: UUID
    bot_key: str
    display_name: str
    status: BotStatus
    config_overrides: Mapping[str, Any]
    last_ticked_at: datetime | None
    next_tick_after: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PricePoint:
    price: Decimal
    captured_at: datetime


@dataclass(frozen=True)
class MarketTradeSample:
    instrument_id: UUID
    side: OrderSide
    quantity: Decimal
    gross_amount: Decimal
    account_id: UUID
    executed_at: datetime


@dataclass(frozen=True)
class PlayerStatsContext:
    observation_count: int = 0
    average_rating: float | None = None
    average_minutes: float | None = None
    goals_per_match: float = 0.0
    assists_per_match: float = 0.0
    clean_sheets_per_match: float = 0.0
    defensive_actions_per_match: float = 0.0
    shots_per_match: float = 0.0
    key_passes_per_match: float = 0.0
    cards_per_match: float = 0.0
    latest_observed_at: datetime | None = None


@dataclass(frozen=True)
class SocialSignalContext:
    mention_count: int = 0
    mention_velocity: float = 0.0
    mention_spike_zscore: float = 0.0
    sentiment_score: float = 0.0
    news_count: int = 0
    trusted_news_count: int = 0
    source_credibility: float = 0.0
    hype_overextension: float = 0.0
    latest_observed_at: datetime | None = None


@dataclass(frozen=True)
class BettingMarketQuote:
    provider_event_id: str
    canonical_selection_key: str
    market_type: str
    outcome_type: str
    line: Decimal | None
    decimal_odds: Decimal
    implied_probability: Decimal
    observed_at: datetime
    kickoff_at: datetime | None = None
    observation_count: int = 1


@dataclass(frozen=True)
class BettingMarketContext:
    quotes: tuple[BettingMarketQuote, ...] = ()

    @property
    def latest_observed_at(self) -> datetime | None:
        if not self.quotes:
            return None
        return max(quote.observed_at for quote in self.quotes)


@dataclass(frozen=True)
class BotPositionContext:
    instrument_id: UUID
    player_id: UUID | None
    club: str | None
    quantity: Decimal
    current_price: Decimal
    market_value: Decimal
    last_trade_price: Decimal | None = None
    unrealized_return_pct: float | None = None


@dataclass(frozen=True)
class BotPortfolioContext:
    account_id: UUID
    portfolio_id: UUID
    cash_balance: Decimal
    total_position_value: Decimal
    total_equity: Decimal
    positions: tuple[BotPositionContext, ...]


@dataclass(frozen=True)
class BotActivityContext:
    daily_trade_count: int
    daily_turnover_cash: Decimal
    last_order_at: datetime | None


@dataclass(frozen=True)
class CandidateInstrumentContext:
    instrument_id: UUID
    player_id: UUID | None
    symbol: str
    display_name: str
    club: str | None
    position: str | None
    current_price: Decimal
    trading_status: str
    current_holding_quantity: Decimal
    current_holding_value: Decimal
    market_value_observation: Decimal | None
    market_value_observed_at: datetime | None
    recent_prices: tuple[PricePoint, ...]
    recent_trades: tuple[MarketTradeSample, ...]
    stats: PlayerStatsContext
    social: SocialSignalContext
    betting: BettingMarketContext = field(default_factory=BettingMarketContext)


@dataclass(frozen=True)
class StrategyDecision:
    instrument_id: UUID
    side: DecisionSide
    alpha_score: float
    expected_return: float
    confidence: float
    suggested_cash_pct: float
    reason: Mapping[str, Any]

    @property
    def priority_score(self) -> float:
        return abs(self.alpha_score) * max(self.confidence, 0.0)


@dataclass(frozen=True)
class OrderIntent:
    bot_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: Decimal
    notional_cash: Decimal
    alpha_score: float
    confidence: float
    reason: Mapping[str, Any]
    request_id: str


@dataclass(frozen=True)
class BotTickContext:
    bot: SyntheticTraderBotRecord
    portfolio: BotPortfolioContext
    activity: BotActivityContext
    candidates: tuple[CandidateInstrumentContext, ...]
    as_of: datetime


@dataclass(frozen=True)
class SyntheticTraderTickOutcome:
    bot_id: UUID
    account_id: UUID
    portfolio_id: UUID
    status: TickOutcomeStatus
    request_id: str | None = None
    instrument_id: UUID | None = None
    side: OrderSide | None = None
    message: str | None = None
    error_code: str | None = None
    error_details: Mapping[str, Any] | None = None
    execution: OrderExecutionRecord | None = None


@dataclass(frozen=True)
class SyntheticTraderTickDiagnostics:
    bot_id: UUID
    strategy_engine: StrategyEngine
    candidates_loaded: int
    candidates_evaluated: int
    candidate_exclusions: Mapping[str, int]
    decisions: Mapping[str, int]
    negative_alpha: Mapping[str, int]
    rejection_reasons: Mapping[str, int]
    recovery_decisions: int = 0
    recovery_orders: int = 0


@dataclass(frozen=True)
class SyntheticTraderTickBatchResult:
    processed_bots: int
    outcomes: tuple[SyntheticTraderTickOutcome, ...]
    diagnostics: tuple[SyntheticTraderTickDiagnostics, ...] = ()

    @property
    def submitted_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is TickOutcomeStatus.SUBMITTED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is TickOutcomeStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is TickOutcomeStatus.FAILED)


@dataclass(frozen=True)
class CreateSyntheticTraderBotCommand:
    account_id: UUID
    config_id: UUID
    bot_key: str
    display_name: str
    status: BotStatus = BotStatus.ACTIVE
    config_overrides: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SpawnSyntheticTraderCommand:
    count: int
    handle_prefix: str | None = None
    display_name_prefix: str | None = None
    config_key: str | None = None
    strategy_engine: StrategyEngine | None = None
    name_style: SpawnNameStyle = SpawnNameStyle.PERSONA
    random_seed: int | None = None
    start_index: int = 1
    status: BotStatus = BotStatus.ACTIVE
    config_overrides: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SpawnedSyntheticTrader:
    account_id: UUID
    portfolio_id: UUID
    bot_id: UUID
    config_id: UUID
    handle: str
    bot_key: str
    display_name: str


@dataclass(frozen=True)
class SpawnSyntheticTraderBatchResult:
    config_key: str
    requested_count: int
    spawned: tuple[SpawnedSyntheticTrader, ...]

    @property
    def spawned_count(self) -> int:
        return len(self.spawned)
