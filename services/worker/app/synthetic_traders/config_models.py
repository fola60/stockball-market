from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping
from uuid import UUID

SUPPORTED_BETTING_MARKET_TYPES = frozenset(
    {
        "GOALSCORER",
        "ASSIST",
        "SCORE_OR_ASSIST",
        "SHOTS",
        "SHOTS_ON_TARGET",
    }
)


# Match events are loaded over this window; an event-reaction bot's own window cannot exceed it.
MAX_EVENT_WINDOW_HOURS = 72


class SyntheticTraderConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ExplainabilityConfig:
    enabled: bool
    record_top_signal_count: int
    include_raw_component_scores: bool


@dataclass(frozen=True)
class ExecutionConfig:
    tick_cadence_minutes: int
    cooldown_minutes: int
    decision_jitter_minutes: int
    trade_probability: float
    size_noise_pct: float
    max_orders_per_tick: int


@dataclass(frozen=True)
class RiskConfig:
    max_trade_cash_pct: float
    min_trade_cash_amount: Decimal
    max_trade_cash_amount: Decimal
    max_daily_trades: int
    max_daily_turnover_pct: float
    volatility_tolerance: float
    max_player_position_pct: float | None = None
    max_team_exposure_pct: float | None = None
    min_cash_reserve_pct: float | None = None
    reduce_size_when_confidence_below: float | None = None


@dataclass(frozen=True)
class CandidateUniverseConfig:
    max_candidates: int
    included_positions: tuple[str, ...]
    excluded_positions: tuple[str, ...]
    included_clubs: tuple[str, ...]
    excluded_clubs: tuple[str, ...]
    min_current_price: Decimal
    max_current_price: Decimal | None
    require_active_instrument: bool
    favorite_clubs: tuple[str, ...] = ()
    favorite_player_ids: tuple[UUID, ...] = ()
    min_recent_trades: int = 0
    min_recent_volume_cash: Decimal = Decimal("0")


@dataclass(frozen=True)
class AlphaDecisionConfig:
    buy_threshold: float
    sell_threshold: float
    min_confidence: float
    hold_band: float
    allow_sells: bool


@dataclass(frozen=True)
class NoiseRandomnessConfig:
    random_alpha_min: float
    random_alpha_max: float
    buy_bias: float
    sell_bias: float
    favorite_club_bias: float
    recognizable_player_bias: float
    recent_mover_bias: float
    holding_bias: float
    activity_floor_minutes: int = 60
    activity_floor_weight: float = 0.0


@dataclass(frozen=True)
class NoiseSizingConfig:
    base_cash_pct: float
    confidence_multiplier: float
    random_size_multiplier_min: float
    random_size_multiplier_max: float
    position_concentration_penalty: float


@dataclass(frozen=True)
class NoiseConfig:
    universe: CandidateUniverseConfig
    randomness: NoiseRandomnessConfig
    signal_weights: Mapping[str, float]
    decision: AlphaDecisionConfig
    risk: RiskConfig
    sizing: NoiseSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


@dataclass(frozen=True)
class MarketMomentumLookbacks:
    price_momentum_minutes: int
    volume_window_minutes: int
    buy_sell_pressure_minutes: int
    volatility_window_days: int
    breakout_window_days: int


@dataclass(frozen=True)
class MarketMomentumInputs:
    min_price_move_pct: float
    breakout_near_high_pct: float
    buy_pressure_threshold: float
    crowded_unique_buyer_threshold: int
    allow_chasing_new_highs: bool
    allow_fading_failed_breakouts: bool


@dataclass(frozen=True)
class MarketMomentumSizingConfig:
    base_cash_pct: float
    confidence_multiplier: float
    momentum_multiplier: float
    volume_multiplier: float
    volatility_size_penalty: float
    position_concentration_penalty: float


@dataclass(frozen=True)
class MarketMomentumConfig:
    universe: CandidateUniverseConfig
    lookbacks: MarketMomentumLookbacks
    signal_weights: Mapping[str, float]
    market_inputs: MarketMomentumInputs
    decision: AlphaDecisionConfig
    risk: RiskConfig
    sizing: MarketMomentumSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


@dataclass(frozen=True)
class StatsValueLookbacks:
    form_matches: int
    market_value_days: int
    price_momentum_days: int


@dataclass(frozen=True)
class StatsInputsConfig:
    rating_weight: float
    goals_weight: float
    assists_weight: float
    clean_sheet_weight: float
    defensive_actions_weight: float
    shots_weight: float
    key_passes_weight: float
    cards_penalty_weight: float
    position_baseline_enabled: bool
    # How much a bot values regular starts and recent form. Older profiles predate these and
    # get the values their engine used to hard-code.
    minutes_weight: float = 0.15
    form_weight: float = 0.1


@dataclass(frozen=True)
class FairValueBlendConfig:
    performance_implied_value: float
    market_value_observation: float
    current_stockball_price: float


@dataclass(frozen=True)
class StatsValueValuationConfig:
    fair_value_blend: FairValueBlendConfig
    min_valuation_gap_to_buy: float
    min_overvaluation_gap_to_sell: float
    cap_extreme_gap_at: float


@dataclass(frozen=True)
class StatsValueSizingConfig:
    base_cash_pct: float
    confidence_multiplier: float
    expected_return_multiplier: float
    volatility_size_penalty: float
    position_concentration_penalty: float


@dataclass(frozen=True)
class StatsValueConfig:
    universe: CandidateUniverseConfig
    lookbacks: StatsValueLookbacks
    signal_weights: Mapping[str, float]
    stats_inputs: StatsInputsConfig
    valuation: StatsValueValuationConfig
    decision: AlphaDecisionConfig
    risk: RiskConfig
    sizing: StatsValueSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


@dataclass(frozen=True)
class SocialSentimentLookbacks:
    price_momentum_hours: int


@dataclass(frozen=True)
class SocialInputsConfig:
    min_mentions: int
    mention_spike_zscore_to_trade: float
    positive_sentiment_threshold: float
    negative_sentiment_threshold: float
    trusted_source_multiplier: float
    untrusted_source_multiplier: float
    contrarian_mode: bool


@dataclass(frozen=True)
class SocialSizingConfig:
    base_cash_pct: float
    confidence_multiplier: float
    hype_multiplier: float
    sentiment_multiplier: float
    overextension_size_penalty: float
    position_concentration_penalty: float


@dataclass(frozen=True)
class SocialSentimentConfig:
    universe: CandidateUniverseConfig
    lookbacks: SocialSentimentLookbacks
    signal_weights: Mapping[str, float]
    social_inputs: SocialInputsConfig
    decision: AlphaDecisionConfig
    risk: RiskConfig
    sizing: SocialSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


@dataclass(frozen=True)
class BettingMarketLookbacks:
    movement_minutes: int
    max_quote_age_minutes: int


@dataclass(frozen=True)
class BettingMarketInputsConfig:
    min_distinct_market_types: int
    min_observations_per_selection: int
    min_implied_probability: float
    movement_scale: float
    market_type_weights: Mapping[str, float]


@dataclass(frozen=True)
class BettingMarketSizingConfig:
    base_cash_pct: float
    confidence_multiplier: float
    movement_multiplier: float
    position_concentration_penalty: float


@dataclass(frozen=True)
class BettingMarketValueConfig:
    universe: CandidateUniverseConfig
    lookbacks: BettingMarketLookbacks
    signal_weights: Mapping[str, float]
    betting_inputs: BettingMarketInputsConfig
    decision: AlphaDecisionConfig
    risk: RiskConfig
    sizing: BettingMarketSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


@dataclass(frozen=True)
class EventReactionLookbacks:
    event_window_hours: int
    betting_movement_minutes: int


@dataclass(frozen=True)
class EventReactionInputsConfig:
    # Appearances shorter than this are ignored: FotMob rates cameos low almost regardless.
    min_minutes: int
    # Rating surprise, in match-rating standard deviations, that counts as a full signal.
    surprise_scale: float
    # How much the bookmakers' pre-match expectation discounts or amplifies the surprise.
    expectation_weight: float
    half_life_hours: float
    reaction_delay_minutes: float
    holding_period_hours: float
    # Stockball price move since the ratings, in the surprise's direction, that counts as
    # fully priced in.
    priced_in_move_pct: float
    movement_scale: float
    market_type_weights: Mapping[str, float]
    # Share of a position sold once `holding_period_hours` have passed since the bot last
    # traded it. Positions the bot was only allocated are never unwound.
    unwind_fraction: float


@dataclass(frozen=True)
class EventReactionSizingConfig:
    base_cash_pct: float
    confidence_multiplier: float
    surprise_multiplier: float
    position_concentration_penalty: float


@dataclass(frozen=True)
class EventReactionConfig:
    universe: CandidateUniverseConfig
    lookbacks: EventReactionLookbacks
    signal_weights: Mapping[str, float]
    event_inputs: EventReactionInputsConfig
    decision: AlphaDecisionConfig
    risk: RiskConfig
    sizing: EventReactionSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


@dataclass(frozen=True)
class PortfolioTargetsConfig:
    target_cash_pct: float
    min_cash_pct: float
    max_cash_pct: float
    max_player_position_pct: float
    max_team_exposure_pct: float
    max_position_count: int
    min_position_cash_value: Decimal


@dataclass(frozen=True)
class RebalanceRulesConfig:
    cash_deploy_threshold_pct: float
    cash_raise_threshold_pct: float
    player_overweight_threshold_pct: float
    team_overweight_threshold_pct: float
    trim_to_target_pct: float
    profit_take_return_pct: float
    loss_reduce_return_pct: float
    allow_new_positions: bool
    allow_full_exit: bool


@dataclass(frozen=True)
class CandidateSelectionConfig:
    max_buy_candidates: int
    max_sell_candidates: int
    prefer_existing_watchlist: bool
    prefer_positive_alpha_when_deploying_cash: bool
    avoid_frozen_or_inactive_instruments: bool


@dataclass(frozen=True)
class PortfolioDecisionConfig:
    allow_buys: bool
    allow_sells: bool


@dataclass(frozen=True)
class PortfolioSizingConfig:
    base_rebalance_pct: float
    cash_drift_multiplier: float
    concentration_multiplier: float
    profit_take_multiplier: float
    volatility_size_penalty: float


@dataclass(frozen=True)
class PortfolioRebalancerConfig:
    portfolio_targets: PortfolioTargetsConfig
    rebalance_rules: RebalanceRulesConfig
    candidate_selection: CandidateSelectionConfig
    signal_weights: Mapping[str, float]
    decision: PortfolioDecisionConfig
    risk: RiskConfig
    sizing: PortfolioSizingConfig
    execution: ExecutionConfig
    explainability: ExplainabilityConfig


StrategyConfig = (
    NoiseConfig
    | MarketMomentumConfig
    | StatsValueConfig
    | SocialSentimentConfig
    | BettingMarketValueConfig
    | EventReactionConfig
    | PortfolioRebalancerConfig
)


DEFAULT_EXPLAINABILITY = ExplainabilityConfig(
    enabled=False,
    record_top_signal_count=0,
    include_raw_component_scores=False,
)
