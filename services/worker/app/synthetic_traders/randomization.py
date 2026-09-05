from __future__ import annotations

from random import Random
from typing import Any, Mapping

from .models import StrategyEngine


PROFILE_VARIATION_BY_CONFIG_KEY: dict[str, float] = {
    "NOISE_RETAIL_BUYER": 0.35,
    "NOISE_RETAIL_SELLER": 0.35,
    "MARKET_MOMENTUM_TRADER": 0.25,
    "STATS_VALUE_CONSERVATIVE": 0.15,
    "STATS_VALUE_AGGRESSIVE": 0.30,
    "SOCIAL_HYPE_CHASER": 0.30,
    "SOCIAL_CONTRARIAN": 0.22,
    "PORTFOLIO_REBALANCER": 0.12,
    "BETTING_MARKET_CONSERVATIVE": 0.15,
    "BETTING_MARKET_AGGRESSIVE": 0.30,
}

ENGINE_RANDOMIZED_FIELDS: dict[StrategyEngine, tuple[str, ...]] = {
    StrategyEngine.NOISE: (
        "signal_weights.*",
        "randomness.buy_bias",
        "randomness.sell_bias",
        "randomness.favorite_club_bias",
        "randomness.recognizable_player_bias",
        "randomness.recent_mover_bias",
        "randomness.holding_bias",
        "sizing.base_cash_pct",
        "sizing.confidence_multiplier",
        "sizing.position_concentration_penalty",
        "execution.trade_probability",
        "execution.size_noise_pct",
    ),
    StrategyEngine.MARKET_MOMENTUM: (
        "signal_weights.*",
        "market_inputs.min_price_move_pct",
        "market_inputs.breakout_near_high_pct",
        "market_inputs.buy_pressure_threshold",
        "sizing.base_cash_pct",
        "sizing.confidence_multiplier",
        "sizing.momentum_multiplier",
        "sizing.volume_multiplier",
        "sizing.volatility_size_penalty",
        "sizing.position_concentration_penalty",
        "execution.trade_probability",
        "execution.size_noise_pct",
    ),
    StrategyEngine.STATS_VALUE: (
        "signal_weights.*",
        "stats_inputs.rating_weight",
        "stats_inputs.goals_weight",
        "stats_inputs.assists_weight",
        "stats_inputs.clean_sheet_weight",
        "stats_inputs.defensive_actions_weight",
        "stats_inputs.shots_weight",
        "stats_inputs.key_passes_weight",
        "stats_inputs.cards_penalty_weight",
        "valuation.fair_value_blend.*",
        "valuation.min_valuation_gap_to_buy",
        "valuation.min_overvaluation_gap_to_sell",
        "sizing.base_cash_pct",
        "sizing.confidence_multiplier",
        "sizing.expected_return_multiplier",
        "sizing.volatility_size_penalty",
        "sizing.position_concentration_penalty",
        "execution.trade_probability",
        "execution.size_noise_pct",
    ),
    StrategyEngine.SOCIAL_SENTIMENT: (
        "signal_weights.*",
        "social_inputs.mention_spike_zscore_to_trade",
        "social_inputs.positive_sentiment_threshold",
        "social_inputs.negative_sentiment_threshold",
        "social_inputs.trusted_source_multiplier",
        "social_inputs.untrusted_source_multiplier",
        "sizing.base_cash_pct",
        "sizing.confidence_multiplier",
        "sizing.hype_multiplier",
        "sizing.sentiment_multiplier",
        "sizing.overextension_size_penalty",
        "sizing.position_concentration_penalty",
        "execution.trade_probability",
        "execution.size_noise_pct",
    ),
    StrategyEngine.PORTFOLIO_REBALANCER: (
        "signal_weights.*",
        "portfolio_targets.target_cash_pct",
        "portfolio_targets.min_cash_pct",
        "portfolio_targets.max_cash_pct",
        "rebalance_rules.cash_deploy_threshold_pct",
        "rebalance_rules.cash_raise_threshold_pct",
        "rebalance_rules.player_overweight_threshold_pct",
        "rebalance_rules.team_overweight_threshold_pct",
        "rebalance_rules.trim_to_target_pct",
        "rebalance_rules.profit_take_return_pct",
        "rebalance_rules.loss_reduce_return_pct",
        "sizing.base_rebalance_pct",
        "sizing.cash_drift_multiplier",
        "sizing.concentration_multiplier",
        "sizing.profit_take_multiplier",
        "sizing.volatility_size_penalty",
        "execution.trade_probability",
        "execution.size_noise_pct",
    ),
    StrategyEngine.BETTING_MARKET_VALUE: (
        "signal_weights.*",
        "betting_inputs.market_type_weights.*",
        "betting_inputs.min_implied_probability",
        "betting_inputs.movement_scale",
        "sizing.base_cash_pct",
        "sizing.confidence_multiplier",
        "sizing.movement_multiplier",
        "sizing.position_concentration_penalty",
        "execution.trade_probability",
        "execution.size_noise_pct",
    ),
}

RATIO_FIELD_SUFFIXES = (
    "_pct",
    "_threshold",
    "_penalty",
    "trade_probability",
    "size_noise_pct",
    "buy_pressure_threshold",
    "positive_sentiment_threshold",
    "min_implied_probability",
)


def build_random_config_overrides(
    *,
    config_key: str,
    strategy_engine: StrategyEngine,
    base_config: Mapping[str, Any],
    random_source: Random,
) -> dict[str, Any]:
    spread = PROFILE_VARIATION_BY_CONFIG_KEY.get(config_key, 0.20)
    overrides: dict[str, Any] = {}
    for path in ENGINE_RANDOMIZED_FIELDS[strategy_engine]:
        if path.endswith(".*"):
            _sample_mapping_section(
                overrides,
                base_config,
                path.removesuffix(".*"),
                spread,
                random_source,
            )
        else:
            _sample_path(overrides, base_config, path, spread, random_source)
    _normalize_fair_value_blend(overrides)
    return overrides


def _sample_mapping_section(
    overrides: dict[str, Any],
    base_config: Mapping[str, Any],
    section_name: str,
    spread: float,
    random_source: Random,
) -> None:
    section_parts = tuple(section_name.split("."))
    section = _get_path(base_config, section_parts)
    if not isinstance(section, Mapping):
        return
    for key, value in section.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        parts = (*section_parts, str(key))
        _set_path(
            overrides,
            parts,
            _sample_value(value, spread, random_source, _is_ratio_path(parts)),
        )


def _sample_path(
    overrides: dict[str, Any],
    base_config: Mapping[str, Any],
    path: str,
    spread: float,
    random_source: Random,
) -> None:
    parts = tuple(path.split("."))
    value = _get_path(base_config, parts)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return
    _set_path(
        overrides,
        parts,
        _sample_value(value, spread, random_source, _is_ratio_path(parts)),
    )


def _sample_value(
    value: int | float,
    spread: float,
    random_source: Random,
    is_ratio: bool,
) -> float:
    numeric_value = float(value)
    if numeric_value == 0:
        return 0.0
    lower = numeric_value * (1 - spread)
    upper = numeric_value * (1 + spread)
    sampled = random_source.uniform(min(lower, upper), max(lower, upper))
    if is_ratio:
        if numeric_value >= 0:
            sampled = max(0.0, min(1.0, sampled))
        else:
            sampled = max(-1.0, min(0.0, sampled))
    return round(sampled, 6)


def _normalize_fair_value_blend(overrides: dict[str, Any]) -> None:
    valuation = overrides.get("valuation")
    if not isinstance(valuation, dict):
        return
    blend = valuation.get("fair_value_blend")
    if not isinstance(blend, dict):
        return
    total = sum(value for value in blend.values() if isinstance(value, int | float))
    if total <= 0:
        return
    for key, value in tuple(blend.items()):
        if isinstance(value, int | float):
            blend[key] = round(float(value) / total, 6)


def _get_path(payload: Mapping[str, Any], parts: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _set_path(overrides: dict[str, Any], parts: tuple[str, ...], value: float) -> None:
    current = overrides
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _is_ratio_path(parts: tuple[str, ...]) -> bool:
    leaf = parts[-1]
    if any(leaf.endswith(suffix) for suffix in RATIO_FIELD_SUFFIXES):
        return True
    if parts[-2:] == ("valuation", "min_valuation_gap_to_buy"):
        return True
    if parts[-2:] == ("valuation", "min_overvaluation_gap_to_sell"):
        return True
    return parts[-2:] == ("market_inputs", "breakout_near_high_pct")
