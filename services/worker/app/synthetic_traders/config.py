from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .models import StrategyEngine


SUPPORTED_BETTING_MARKET_TYPES = frozenset(
    {
        "GOALSCORER",
        "ASSIST",
        "SCORE_OR_ASSIST",
        "SHOTS",
        "SHOTS_ON_TARGET",
    }
)


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
    sell_only_if_position_exists: bool


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
    baseline_matches: int
    minutes_matches: int
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
    mention_window_minutes: int
    baseline_window_days: int
    news_window_hours: int
    price_momentum_hours: int
    sentiment_window_hours: int


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
    rebalance_threshold: float
    min_confidence: float
    allow_buys: bool
    allow_sells: bool
    sell_only_if_position_exists: bool


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
    | PortfolioRebalancerConfig
)


DEFAULT_EXPLAINABILITY = ExplainabilityConfig(
    enabled=False,
    record_top_signal_count=0,
    include_raw_component_scores=False,
)


def parse_strategy_config(
    engine: StrategyEngine,
    raw_config: Mapping[str, Any],
) -> StrategyConfig:
    payload = _mapping(raw_config, "config")
    if engine is StrategyEngine.NOISE:
        return NoiseConfig(
            universe=_parse_universe(payload),
            randomness=_parse_noise_randomness(payload),
            signal_weights=_parse_float_mapping(payload, "signal_weights"),
            decision=_parse_alpha_decision(payload),
            risk=_parse_risk(payload),
            sizing=_parse_noise_sizing(payload),
            execution=_parse_execution(payload),
            explainability=_parse_explainability(payload),
        )
    if engine is StrategyEngine.MARKET_MOMENTUM:
        return MarketMomentumConfig(
            universe=_parse_universe(payload),
            lookbacks=_parse_market_momentum_lookbacks(payload),
            signal_weights=_parse_float_mapping(payload, "signal_weights"),
            market_inputs=_parse_market_momentum_inputs(payload),
            decision=_parse_alpha_decision(payload),
            risk=_parse_risk(payload),
            sizing=_parse_market_momentum_sizing(payload),
            execution=_parse_execution(payload),
            explainability=_parse_explainability(payload),
        )
    if engine is StrategyEngine.STATS_VALUE:
        return StatsValueConfig(
            universe=_parse_universe(payload),
            lookbacks=_parse_stats_value_lookbacks(payload),
            signal_weights=_parse_float_mapping(payload, "signal_weights"),
            stats_inputs=_parse_stats_inputs(payload),
            valuation=_parse_stats_value_valuation(payload),
            decision=_parse_alpha_decision(payload),
            risk=_parse_risk(payload),
            sizing=_parse_stats_value_sizing(payload),
            execution=_parse_execution(payload),
            explainability=_parse_explainability(payload),
        )
    if engine is StrategyEngine.SOCIAL_SENTIMENT:
        return SocialSentimentConfig(
            universe=_parse_universe(payload),
            lookbacks=_parse_social_lookbacks(payload),
            signal_weights=_parse_float_mapping(payload, "signal_weights"),
            social_inputs=_parse_social_inputs(payload),
            decision=_parse_alpha_decision(payload),
            risk=_parse_risk(payload),
            sizing=_parse_social_sizing(payload),
            execution=_parse_execution(payload),
            explainability=_parse_explainability(payload),
        )
    if engine is StrategyEngine.BETTING_MARKET_VALUE:
        return BettingMarketValueConfig(
            universe=_parse_universe(payload),
            lookbacks=_parse_betting_market_lookbacks(payload),
            signal_weights=_parse_float_mapping(payload, "signal_weights"),
            betting_inputs=_parse_betting_market_inputs(payload),
            decision=_parse_alpha_decision(payload),
            risk=_parse_risk(payload),
            sizing=_parse_betting_market_sizing(payload),
            execution=_parse_execution(payload),
            explainability=_parse_explainability(payload),
        )
    if engine is StrategyEngine.PORTFOLIO_REBALANCER:
        return PortfolioRebalancerConfig(
            portfolio_targets=_parse_portfolio_targets(payload),
            rebalance_rules=_parse_rebalance_rules(payload),
            candidate_selection=_parse_candidate_selection(payload),
            signal_weights=_parse_float_mapping(payload, "signal_weights"),
            decision=_parse_portfolio_decision(payload),
            risk=_parse_risk(payload),
            sizing=_parse_portfolio_sizing(payload),
            execution=_parse_execution(payload),
            explainability=_parse_explainability(payload),
        )
    raise SyntheticTraderConfigError(f"unsupported strategy engine: {engine.value}")


def apply_config_overrides(
    base_config: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    merged = _deep_copy_mapping(base_config)
    for key, value in overrides.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = apply_config_overrides(
                _mapping(merged[key], f"config.{key}"),
                _mapping(value, f"overrides.{key}"),
            )
        else:
            merged[key] = _deep_copy_value(value)
    return merged


def _parse_universe(payload: Mapping[str, Any]) -> CandidateUniverseConfig:
    universe = _section(payload, "universe")
    return CandidateUniverseConfig(
        max_candidates=_positive_int(universe.get("max_candidates"), "universe.max_candidates"),
        included_positions=_string_tuple(universe.get("included_positions"), "universe.included_positions"),
        excluded_positions=_string_tuple(universe.get("excluded_positions"), "universe.excluded_positions"),
        included_clubs=_string_tuple(universe.get("included_clubs"), "universe.included_clubs"),
        excluded_clubs=_string_tuple(universe.get("excluded_clubs"), "universe.excluded_clubs"),
        min_current_price=_non_negative_decimal(
            universe.get("min_current_price"),
            "universe.min_current_price",
        ),
        max_current_price=_optional_decimal(universe.get("max_current_price"), "universe.max_current_price"),
        require_active_instrument=_bool(
            universe.get("require_active_instrument", True),
            "universe.require_active_instrument",
        ),
        favorite_clubs=_string_tuple(universe.get("favorite_clubs", ()), "universe.favorite_clubs"),
        favorite_player_ids=_uuid_tuple(universe.get("favorite_player_ids", ()), "universe.favorite_player_ids"),
        min_recent_trades=_non_negative_int(universe.get("min_recent_trades", 0), "universe.min_recent_trades"),
        min_recent_volume_cash=_non_negative_decimal(
            universe.get("min_recent_volume_cash", "0"),
            "universe.min_recent_volume_cash",
        ),
    )


def _parse_noise_randomness(payload: Mapping[str, Any]) -> NoiseRandomnessConfig:
    randomness = _section(payload, "randomness")
    minimum = _float(randomness.get("random_alpha_min"), "randomness.random_alpha_min")
    maximum = _float(randomness.get("random_alpha_max"), "randomness.random_alpha_max")
    if maximum < minimum:
        raise SyntheticTraderConfigError(
            "randomness.random_alpha_max must be greater than or equal to random_alpha_min"
        )
    return NoiseRandomnessConfig(
        random_alpha_min=minimum,
        random_alpha_max=maximum,
        buy_bias=_float(randomness.get("buy_bias"), "randomness.buy_bias"),
        sell_bias=_float(randomness.get("sell_bias"), "randomness.sell_bias"),
        favorite_club_bias=_float(
            randomness.get("favorite_club_bias"),
            "randomness.favorite_club_bias",
        ),
        recognizable_player_bias=_float(
            randomness.get("recognizable_player_bias"),
            "randomness.recognizable_player_bias",
        ),
        recent_mover_bias=_float(
            randomness.get("recent_mover_bias"),
            "randomness.recent_mover_bias",
        ),
        holding_bias=_float(randomness.get("holding_bias"), "randomness.holding_bias"),
    )


def _parse_noise_sizing(payload: Mapping[str, Any]) -> NoiseSizingConfig:
    sizing = _section(payload, "sizing")
    minimum = _positive_float(
        sizing.get("random_size_multiplier_min"),
        "sizing.random_size_multiplier_min",
    )
    maximum = _positive_float(
        sizing.get("random_size_multiplier_max"),
        "sizing.random_size_multiplier_max",
    )
    if maximum < minimum:
        raise SyntheticTraderConfigError(
            "sizing.random_size_multiplier_max must be greater than or equal to random_size_multiplier_min"
        )
    return NoiseSizingConfig(
        base_cash_pct=_ratio(sizing.get("base_cash_pct"), "sizing.base_cash_pct"),
        confidence_multiplier=_positive_float(
            sizing.get("confidence_multiplier"),
            "sizing.confidence_multiplier",
        ),
        random_size_multiplier_min=minimum,
        random_size_multiplier_max=maximum,
        position_concentration_penalty=_ratio(
            sizing.get("position_concentration_penalty"),
            "sizing.position_concentration_penalty",
        ),
    )


def _parse_market_momentum_lookbacks(payload: Mapping[str, Any]) -> MarketMomentumLookbacks:
    lookbacks = _section(payload, "lookbacks")
    return MarketMomentumLookbacks(
        price_momentum_minutes=_positive_int(
            lookbacks.get("price_momentum_minutes"),
            "lookbacks.price_momentum_minutes",
        ),
        volume_window_minutes=_positive_int(
            lookbacks.get("volume_window_minutes"),
            "lookbacks.volume_window_minutes",
        ),
        buy_sell_pressure_minutes=_positive_int(
            lookbacks.get("buy_sell_pressure_minutes"),
            "lookbacks.buy_sell_pressure_minutes",
        ),
        volatility_window_days=_positive_int(
            lookbacks.get("volatility_window_days"),
            "lookbacks.volatility_window_days",
        ),
        breakout_window_days=_positive_int(
            lookbacks.get("breakout_window_days"),
            "lookbacks.breakout_window_days",
        ),
    )


def _parse_market_momentum_inputs(payload: Mapping[str, Any]) -> MarketMomentumInputs:
    inputs = _section(payload, "market_inputs")
    return MarketMomentumInputs(
        min_price_move_pct=_ratio(inputs.get("min_price_move_pct"), "market_inputs.min_price_move_pct"),
        breakout_near_high_pct=_ratio(
            inputs.get("breakout_near_high_pct"),
            "market_inputs.breakout_near_high_pct",
        ),
        buy_pressure_threshold=_ratio(
            inputs.get("buy_pressure_threshold"),
            "market_inputs.buy_pressure_threshold",
        ),
        crowded_unique_buyer_threshold=_positive_int(
            inputs.get("crowded_unique_buyer_threshold"),
            "market_inputs.crowded_unique_buyer_threshold",
        ),
        allow_chasing_new_highs=_bool(
            inputs.get("allow_chasing_new_highs", True),
            "market_inputs.allow_chasing_new_highs",
        ),
        allow_fading_failed_breakouts=_bool(
            inputs.get("allow_fading_failed_breakouts", False),
            "market_inputs.allow_fading_failed_breakouts",
        ),
    )


def _parse_market_momentum_sizing(payload: Mapping[str, Any]) -> MarketMomentumSizingConfig:
    sizing = _section(payload, "sizing")
    return MarketMomentumSizingConfig(
        base_cash_pct=_ratio(sizing.get("base_cash_pct"), "sizing.base_cash_pct"),
        confidence_multiplier=_positive_float(
            sizing.get("confidence_multiplier"),
            "sizing.confidence_multiplier",
        ),
        momentum_multiplier=_positive_float(
            sizing.get("momentum_multiplier"),
            "sizing.momentum_multiplier",
        ),
        volume_multiplier=_positive_float(
            sizing.get("volume_multiplier"),
            "sizing.volume_multiplier",
        ),
        volatility_size_penalty=_ratio(
            sizing.get("volatility_size_penalty"),
            "sizing.volatility_size_penalty",
        ),
        position_concentration_penalty=_ratio(
            sizing.get("position_concentration_penalty"),
            "sizing.position_concentration_penalty",
        ),
    )


def _parse_stats_value_lookbacks(payload: Mapping[str, Any]) -> StatsValueLookbacks:
    lookbacks = _section(payload, "lookbacks")
    return StatsValueLookbacks(
        form_matches=_positive_int(lookbacks.get("form_matches"), "lookbacks.form_matches"),
        baseline_matches=_positive_int(
            lookbacks.get("baseline_matches"),
            "lookbacks.baseline_matches",
        ),
        minutes_matches=_positive_int(
            lookbacks.get("minutes_matches"),
            "lookbacks.minutes_matches",
        ),
        market_value_days=_positive_int(
            lookbacks.get("market_value_days"),
            "lookbacks.market_value_days",
        ),
        price_momentum_days=_positive_int(
            lookbacks.get("price_momentum_days"),
            "lookbacks.price_momentum_days",
        ),
    )


def _parse_stats_inputs(payload: Mapping[str, Any]) -> StatsInputsConfig:
    stats_inputs = _section(payload, "stats_inputs")
    return StatsInputsConfig(
        rating_weight=_float(stats_inputs.get("rating_weight"), "stats_inputs.rating_weight"),
        goals_weight=_float(stats_inputs.get("goals_weight"), "stats_inputs.goals_weight"),
        assists_weight=_float(stats_inputs.get("assists_weight"), "stats_inputs.assists_weight"),
        clean_sheet_weight=_float(
            stats_inputs.get("clean_sheet_weight"),
            "stats_inputs.clean_sheet_weight",
        ),
        defensive_actions_weight=_float(
            stats_inputs.get("defensive_actions_weight"),
            "stats_inputs.defensive_actions_weight",
        ),
        shots_weight=_float(stats_inputs.get("shots_weight"), "stats_inputs.shots_weight"),
        key_passes_weight=_float(
            stats_inputs.get("key_passes_weight"),
            "stats_inputs.key_passes_weight",
        ),
        cards_penalty_weight=_float(
            stats_inputs.get("cards_penalty_weight"),
            "stats_inputs.cards_penalty_weight",
        ),
        position_baseline_enabled=_bool(
            stats_inputs.get("position_baseline_enabled", True),
            "stats_inputs.position_baseline_enabled",
        ),
    )


def _parse_stats_value_valuation(payload: Mapping[str, Any]) -> StatsValueValuationConfig:
    valuation = _section(payload, "valuation")
    blend = _section(valuation, "fair_value_blend", parent="valuation")
    return StatsValueValuationConfig(
        fair_value_blend=FairValueBlendConfig(
            performance_implied_value=_ratio(
                blend.get("performance_implied_value"),
                "valuation.fair_value_blend.performance_implied_value",
            ),
            market_value_observation=_ratio(
                blend.get("market_value_observation"),
                "valuation.fair_value_blend.market_value_observation",
            ),
            current_stockball_price=_ratio(
                blend.get("current_stockball_price"),
                "valuation.fair_value_blend.current_stockball_price",
            ),
        ),
        min_valuation_gap_to_buy=_ratio(
            valuation.get("min_valuation_gap_to_buy"),
            "valuation.min_valuation_gap_to_buy",
        ),
        min_overvaluation_gap_to_sell=_ratio(
            valuation.get("min_overvaluation_gap_to_sell"),
            "valuation.min_overvaluation_gap_to_sell",
        ),
        cap_extreme_gap_at=_positive_float(
            valuation.get("cap_extreme_gap_at"),
            "valuation.cap_extreme_gap_at",
        ),
    )


def _parse_stats_value_sizing(payload: Mapping[str, Any]) -> StatsValueSizingConfig:
    sizing = _section(payload, "sizing")
    return StatsValueSizingConfig(
        base_cash_pct=_ratio(sizing.get("base_cash_pct"), "sizing.base_cash_pct"),
        confidence_multiplier=_positive_float(
            sizing.get("confidence_multiplier"),
            "sizing.confidence_multiplier",
        ),
        expected_return_multiplier=_positive_float(
            sizing.get("expected_return_multiplier"),
            "sizing.expected_return_multiplier",
        ),
        volatility_size_penalty=_ratio(
            sizing.get("volatility_size_penalty"),
            "sizing.volatility_size_penalty",
        ),
        position_concentration_penalty=_ratio(
            sizing.get("position_concentration_penalty"),
            "sizing.position_concentration_penalty",
        ),
    )


def _parse_social_lookbacks(payload: Mapping[str, Any]) -> SocialSentimentLookbacks:
    lookbacks = _section(payload, "lookbacks")
    return SocialSentimentLookbacks(
        mention_window_minutes=_positive_int(
            lookbacks.get("mention_window_minutes"),
            "lookbacks.mention_window_minutes",
        ),
        baseline_window_days=_positive_int(
            lookbacks.get("baseline_window_days"),
            "lookbacks.baseline_window_days",
        ),
        news_window_hours=_positive_int(
            lookbacks.get("news_window_hours"),
            "lookbacks.news_window_hours",
        ),
        price_momentum_hours=_positive_int(
            lookbacks.get("price_momentum_hours"),
            "lookbacks.price_momentum_hours",
        ),
        sentiment_window_hours=_positive_int(
            lookbacks.get("sentiment_window_hours"),
            "lookbacks.sentiment_window_hours",
        ),
    )


def _parse_social_inputs(payload: Mapping[str, Any]) -> SocialInputsConfig:
    inputs = _section(payload, "social_inputs")
    return SocialInputsConfig(
        min_mentions=_non_negative_int(inputs.get("min_mentions"), "social_inputs.min_mentions"),
        mention_spike_zscore_to_trade=_float(
            inputs.get("mention_spike_zscore_to_trade"),
            "social_inputs.mention_spike_zscore_to_trade",
        ),
        positive_sentiment_threshold=_float(
            inputs.get("positive_sentiment_threshold"),
            "social_inputs.positive_sentiment_threshold",
        ),
        negative_sentiment_threshold=_float(
            inputs.get("negative_sentiment_threshold"),
            "social_inputs.negative_sentiment_threshold",
        ),
        trusted_source_multiplier=_positive_float(
            inputs.get("trusted_source_multiplier"),
            "social_inputs.trusted_source_multiplier",
        ),
        untrusted_source_multiplier=_positive_float(
            inputs.get("untrusted_source_multiplier"),
            "social_inputs.untrusted_source_multiplier",
        ),
        contrarian_mode=_bool(
            inputs.get("contrarian_mode", False),
            "social_inputs.contrarian_mode",
        ),
    )


def _parse_social_sizing(payload: Mapping[str, Any]) -> SocialSizingConfig:
    sizing = _section(payload, "sizing")
    return SocialSizingConfig(
        base_cash_pct=_ratio(sizing.get("base_cash_pct"), "sizing.base_cash_pct"),
        confidence_multiplier=_positive_float(
            sizing.get("confidence_multiplier"),
            "sizing.confidence_multiplier",
        ),
        hype_multiplier=_positive_float(
            sizing.get("hype_multiplier"),
            "sizing.hype_multiplier",
        ),
        sentiment_multiplier=_positive_float(
            sizing.get("sentiment_multiplier"),
            "sizing.sentiment_multiplier",
        ),
        overextension_size_penalty=_ratio(
            sizing.get("overextension_size_penalty"),
            "sizing.overextension_size_penalty",
        ),
        position_concentration_penalty=_ratio(
            sizing.get("position_concentration_penalty"),
            "sizing.position_concentration_penalty",
        ),
    )


def _parse_betting_market_lookbacks(
    payload: Mapping[str, Any],
) -> BettingMarketLookbacks:
    lookbacks = _section(payload, "lookbacks")
    movement_minutes = _positive_int(
        lookbacks.get("movement_minutes"),
        "lookbacks.movement_minutes",
    )
    max_quote_age_minutes = _positive_int(
        lookbacks.get("max_quote_age_minutes"),
        "lookbacks.max_quote_age_minutes",
    )
    if max_quote_age_minutes > movement_minutes:
        raise SyntheticTraderConfigError(
            "lookbacks.max_quote_age_minutes must not exceed movement_minutes"
        )
    return BettingMarketLookbacks(
        movement_minutes=movement_minutes,
        max_quote_age_minutes=max_quote_age_minutes,
    )


def _parse_betting_market_inputs(
    payload: Mapping[str, Any],
) -> BettingMarketInputsConfig:
    inputs = _section(payload, "betting_inputs")
    raw_weights = _section(
        inputs,
        "market_type_weights",
        parent="betting_inputs",
    )
    market_type_weights: dict[str, float] = {}
    for market_type, value in raw_weights.items():
        normalized_type = str(market_type).strip().upper()
        if normalized_type not in SUPPORTED_BETTING_MARKET_TYPES:
            raise SyntheticTraderConfigError(
                "betting_inputs.market_type_weights contains unsupported market type "
                f"{market_type!r}"
            )
        market_type_weights[normalized_type] = _positive_float(
            value,
            f"betting_inputs.market_type_weights.{market_type}",
        )
    if not market_type_weights:
        raise SyntheticTraderConfigError(
            "betting_inputs.market_type_weights must not be empty"
        )
    min_distinct_market_types = _positive_int(
        inputs.get("min_distinct_market_types"),
        "betting_inputs.min_distinct_market_types",
    )
    if min_distinct_market_types > len(market_type_weights):
        raise SyntheticTraderConfigError(
            "betting_inputs.min_distinct_market_types cannot exceed the number "
            "of configured market types"
        )
    return BettingMarketInputsConfig(
        min_distinct_market_types=min_distinct_market_types,
        min_observations_per_selection=_positive_int(
            inputs.get("min_observations_per_selection"),
            "betting_inputs.min_observations_per_selection",
        ),
        min_implied_probability=_ratio(
            inputs.get("min_implied_probability"),
            "betting_inputs.min_implied_probability",
        ),
        movement_scale=_positive_float(
            inputs.get("movement_scale"),
            "betting_inputs.movement_scale",
        ),
        market_type_weights=market_type_weights,
    )


def _parse_betting_market_sizing(
    payload: Mapping[str, Any],
) -> BettingMarketSizingConfig:
    sizing = _section(payload, "sizing")
    return BettingMarketSizingConfig(
        base_cash_pct=_ratio(sizing.get("base_cash_pct"), "sizing.base_cash_pct"),
        confidence_multiplier=_positive_float(
            sizing.get("confidence_multiplier"),
            "sizing.confidence_multiplier",
        ),
        movement_multiplier=_positive_float(
            sizing.get("movement_multiplier"),
            "sizing.movement_multiplier",
        ),
        position_concentration_penalty=_ratio(
            sizing.get("position_concentration_penalty"),
            "sizing.position_concentration_penalty",
        ),
    )


def _parse_portfolio_targets(payload: Mapping[str, Any]) -> PortfolioTargetsConfig:
    targets = _section(payload, "portfolio_targets")
    return PortfolioTargetsConfig(
        target_cash_pct=_ratio(targets.get("target_cash_pct"), "portfolio_targets.target_cash_pct"),
        min_cash_pct=_ratio(targets.get("min_cash_pct"), "portfolio_targets.min_cash_pct"),
        max_cash_pct=_ratio(targets.get("max_cash_pct"), "portfolio_targets.max_cash_pct"),
        max_player_position_pct=_ratio(
            targets.get("max_player_position_pct"),
            "portfolio_targets.max_player_position_pct",
        ),
        max_team_exposure_pct=_ratio(
            targets.get("max_team_exposure_pct"),
            "portfolio_targets.max_team_exposure_pct",
        ),
        max_position_count=_positive_int(
            targets.get("max_position_count"),
            "portfolio_targets.max_position_count",
        ),
        min_position_cash_value=_non_negative_decimal(
            targets.get("min_position_cash_value"),
            "portfolio_targets.min_position_cash_value",
        ),
    )


def _parse_rebalance_rules(payload: Mapping[str, Any]) -> RebalanceRulesConfig:
    rules = _section(payload, "rebalance_rules")
    return RebalanceRulesConfig(
        cash_deploy_threshold_pct=_ratio(
            rules.get("cash_deploy_threshold_pct"),
            "rebalance_rules.cash_deploy_threshold_pct",
        ),
        cash_raise_threshold_pct=_ratio(
            rules.get("cash_raise_threshold_pct"),
            "rebalance_rules.cash_raise_threshold_pct",
        ),
        player_overweight_threshold_pct=_ratio(
            rules.get("player_overweight_threshold_pct"),
            "rebalance_rules.player_overweight_threshold_pct",
        ),
        team_overweight_threshold_pct=_ratio(
            rules.get("team_overweight_threshold_pct"),
            "rebalance_rules.team_overweight_threshold_pct",
        ),
        trim_to_target_pct=_ratio(
            rules.get("trim_to_target_pct"),
            "rebalance_rules.trim_to_target_pct",
        ),
        profit_take_return_pct=_float(
            rules.get("profit_take_return_pct"),
            "rebalance_rules.profit_take_return_pct",
        ),
        loss_reduce_return_pct=_float(
            rules.get("loss_reduce_return_pct"),
            "rebalance_rules.loss_reduce_return_pct",
        ),
        allow_new_positions=_bool(
            rules.get("allow_new_positions", True),
            "rebalance_rules.allow_new_positions",
        ),
        allow_full_exit=_bool(
            rules.get("allow_full_exit", False),
            "rebalance_rules.allow_full_exit",
        ),
    )


def _parse_candidate_selection(payload: Mapping[str, Any]) -> CandidateSelectionConfig:
    selection = _section(payload, "candidate_selection")
    return CandidateSelectionConfig(
        max_buy_candidates=_positive_int(
            selection.get("max_buy_candidates"),
            "candidate_selection.max_buy_candidates",
        ),
        max_sell_candidates=_positive_int(
            selection.get("max_sell_candidates"),
            "candidate_selection.max_sell_candidates",
        ),
        prefer_existing_watchlist=_bool(
            selection.get("prefer_existing_watchlist", True),
            "candidate_selection.prefer_existing_watchlist",
        ),
        prefer_positive_alpha_when_deploying_cash=_bool(
            selection.get("prefer_positive_alpha_when_deploying_cash", True),
            "candidate_selection.prefer_positive_alpha_when_deploying_cash",
        ),
        avoid_frozen_or_inactive_instruments=_bool(
            selection.get("avoid_frozen_or_inactive_instruments", True),
            "candidate_selection.avoid_frozen_or_inactive_instruments",
        ),
    )


def _parse_portfolio_decision(payload: Mapping[str, Any]) -> PortfolioDecisionConfig:
    decision = _section(payload, "decision")
    return PortfolioDecisionConfig(
        rebalance_threshold=_ratio(
            decision.get("rebalance_threshold"),
            "decision.rebalance_threshold",
        ),
        min_confidence=_ratio(
            decision.get("min_confidence"),
            "decision.min_confidence",
        ),
        allow_buys=_bool(decision.get("allow_buys", True), "decision.allow_buys"),
        allow_sells=_bool(decision.get("allow_sells", True), "decision.allow_sells"),
        sell_only_if_position_exists=_bool(
            decision.get("sell_only_if_position_exists", True),
            "decision.sell_only_if_position_exists",
        ),
    )


def _parse_portfolio_sizing(payload: Mapping[str, Any]) -> PortfolioSizingConfig:
    sizing = _section(payload, "sizing")
    return PortfolioSizingConfig(
        base_rebalance_pct=_ratio(
            sizing.get("base_rebalance_pct"),
            "sizing.base_rebalance_pct",
        ),
        cash_drift_multiplier=_positive_float(
            sizing.get("cash_drift_multiplier"),
            "sizing.cash_drift_multiplier",
        ),
        concentration_multiplier=_positive_float(
            sizing.get("concentration_multiplier"),
            "sizing.concentration_multiplier",
        ),
        profit_take_multiplier=_positive_float(
            sizing.get("profit_take_multiplier"),
            "sizing.profit_take_multiplier",
        ),
        volatility_size_penalty=_ratio(
            sizing.get("volatility_size_penalty"),
            "sizing.volatility_size_penalty",
        ),
    )


def _parse_alpha_decision(payload: Mapping[str, Any]) -> AlphaDecisionConfig:
    decision = _section(payload, "decision")
    return AlphaDecisionConfig(
        buy_threshold=_float(decision.get("buy_threshold"), "decision.buy_threshold"),
        sell_threshold=_float(decision.get("sell_threshold"), "decision.sell_threshold"),
        min_confidence=_ratio(decision.get("min_confidence"), "decision.min_confidence"),
        hold_band=_ratio(decision.get("hold_band"), "decision.hold_band"),
        allow_sells=_bool(decision.get("allow_sells", True), "decision.allow_sells"),
        sell_only_if_position_exists=_bool(
            decision.get("sell_only_if_position_exists", True),
            "decision.sell_only_if_position_exists",
        ),
    )


def _parse_risk(payload: Mapping[str, Any]) -> RiskConfig:
    risk = _section(payload, "risk")
    return RiskConfig(
        max_trade_cash_pct=_ratio(
            risk.get("max_trade_cash_pct"),
            "risk.max_trade_cash_pct",
        ),
        min_trade_cash_amount=_non_negative_decimal(
            risk.get("min_trade_cash_amount"),
            "risk.min_trade_cash_amount",
        ),
        max_trade_cash_amount=_non_negative_decimal(
            risk.get("max_trade_cash_amount"),
            "risk.max_trade_cash_amount",
        ),
        max_player_position_pct=_optional_ratio(
            risk.get("max_player_position_pct"),
            "risk.max_player_position_pct",
        ),
        max_team_exposure_pct=_optional_ratio(
            risk.get("max_team_exposure_pct"),
            "risk.max_team_exposure_pct",
        ),
        min_cash_reserve_pct=_optional_ratio(
            risk.get("min_cash_reserve_pct"),
            "risk.min_cash_reserve_pct",
        ),
        max_daily_trades=_positive_int(
            risk.get("max_daily_trades"),
            "risk.max_daily_trades",
        ),
        max_daily_turnover_pct=_ratio(
            risk.get("max_daily_turnover_pct", 1.0),
            "risk.max_daily_turnover_pct",
        ),
        volatility_tolerance=_ratio(
            risk.get("volatility_tolerance"),
            "risk.volatility_tolerance",
        ),
        reduce_size_when_confidence_below=_optional_ratio(
            risk.get("reduce_size_when_confidence_below"),
            "risk.reduce_size_when_confidence_below",
        ),
    )


def _parse_execution(payload: Mapping[str, Any]) -> ExecutionConfig:
    execution = _section(payload, "execution")
    return ExecutionConfig(
        tick_cadence_minutes=_positive_int(
            execution.get("tick_cadence_minutes"),
            "execution.tick_cadence_minutes",
        ),
        cooldown_minutes=_non_negative_int(
            execution.get("cooldown_minutes"),
            "execution.cooldown_minutes",
        ),
        decision_jitter_minutes=_non_negative_int(
            execution.get("decision_jitter_minutes"),
            "execution.decision_jitter_minutes",
        ),
        trade_probability=_ratio(
            execution.get("trade_probability"),
            "execution.trade_probability",
        ),
        size_noise_pct=_ratio(
            execution.get("size_noise_pct"),
            "execution.size_noise_pct",
        ),
        max_orders_per_tick=_positive_int(
            execution.get("max_orders_per_tick"),
            "execution.max_orders_per_tick",
        ),
    )


def _parse_explainability(payload: Mapping[str, Any]) -> ExplainabilityConfig:
    raw_section = payload.get("explainability")
    if raw_section is None:
        return DEFAULT_EXPLAINABILITY
    explainability = _mapping(raw_section, "explainability")
    return ExplainabilityConfig(
        enabled=_bool(explainability.get("enabled", False), "explainability.enabled"),
        record_top_signal_count=_non_negative_int(
            explainability.get("record_top_signal_count", 0),
            "explainability.record_top_signal_count",
        ),
        include_raw_component_scores=_bool(
            explainability.get("include_raw_component_scores", False),
            "explainability.include_raw_component_scores",
        ),
    )


def _parse_float_mapping(payload: Mapping[str, Any], key: str) -> dict[str, float]:
    section = _section(payload, key)
    parsed: dict[str, float] = {}
    for item_key, item_value in section.items():
        parsed[str(item_key)] = _float(item_value, f"{key}.{item_key}")
    if not parsed:
        raise SyntheticTraderConfigError(f"{key} must not be empty")
    return parsed


def _section(
    payload: Mapping[str, Any],
    key: str,
    *,
    parent: str = "config",
) -> Mapping[str, Any]:
    value = payload.get(key)
    return _mapping(value, f"{parent}.{key}")


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SyntheticTraderConfigError(f"{path} must be an object")
    return value


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise SyntheticTraderConfigError(f"{path} must be a list")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SyntheticTraderConfigError(f"{path} entries must be strings")
        item_value = item.strip()
        if not item_value:
            raise SyntheticTraderConfigError(f"{path} entries must not be empty")
        normalized.append(item_value)
    return tuple(normalized)


def _uuid_tuple(value: object, path: str) -> tuple[UUID, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise SyntheticTraderConfigError(f"{path} must be a list")
    items: list[UUID] = []
    for item in value:
        try:
            items.append(UUID(str(item)))
        except ValueError as exc:
            raise SyntheticTraderConfigError(f"{path} contains an invalid UUID") from exc
    return tuple(items)


def _bool(value: object, path: str) -> bool:
    if isinstance(value, bool):
        return value
    raise SyntheticTraderConfigError(f"{path} must be a boolean")


def _float(value: object, path: str) -> float:
    if isinstance(value, bool):
        raise SyntheticTraderConfigError(f"{path} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise SyntheticTraderConfigError(f"{path} must be a number") from exc


def _positive_float(value: object, path: str) -> float:
    parsed = _float(value, path)
    if parsed <= 0:
        raise SyntheticTraderConfigError(f"{path} must be greater than 0")
    return parsed


def _ratio(value: object, path: str) -> float:
    parsed = _float(value, path)
    if parsed < 0 or parsed > 1:
        raise SyntheticTraderConfigError(f"{path} must be between 0 and 1")
    return parsed


def _optional_ratio(value: object, path: str) -> float | None:
    if value is None:
        return None
    return _ratio(value, path)


def _decimal(value: object, path: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SyntheticTraderConfigError(f"{path} must be a decimal value") from exc


def _optional_decimal(value: object, path: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, path)


def _non_negative_decimal(value: object, path: str) -> Decimal:
    parsed = _decimal(value, path)
    if parsed < 0:
        raise SyntheticTraderConfigError(f"{path} must be greater than or equal to 0")
    return parsed


def _positive_int(value: object, path: str) -> int:
    parsed = _int(value, path)
    if parsed <= 0:
        raise SyntheticTraderConfigError(f"{path} must be greater than 0")
    return parsed


def _non_negative_int(value: object, path: str) -> int:
    parsed = _int(value, path)
    if parsed < 0:
        raise SyntheticTraderConfigError(f"{path} must be greater than or equal to 0")
    return parsed


def _int(value: object, path: str) -> int:
    if isinstance(value, bool):
        raise SyntheticTraderConfigError(f"{path} must be an integer")
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise SyntheticTraderConfigError(f"{path} must be an integer") from exc


def _deep_copy_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _deep_copy_value(value) for key, value in payload.items()}


def _deep_copy_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return _deep_copy_mapping(value)
    if isinstance(value, list):
        return [_deep_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return [_deep_copy_value(item) for item in value]
    return value
