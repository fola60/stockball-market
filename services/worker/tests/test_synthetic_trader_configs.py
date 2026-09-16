from __future__ import annotations

import unittest
from uuid import uuid4

from app.synthetic_traders import (
    BettingMarketValueConfig,
    MarketMomentumConfig,
    NoiseConfig,
    PortfolioRebalancerConfig,
    SocialSentimentConfig,
    StatsValueConfig,
    StrategyEngine,
    SyntheticTraderConfigError,
    parse_strategy_config,
)


class SyntheticTraderConfigTests(unittest.TestCase):
    def test_parse_noise_config_validates_uuid_favorites(self) -> None:
        favorite_player_id = uuid4()

        config = parse_strategy_config(
            StrategyEngine.NOISE,
            {
                "universe": {
                    "max_candidates": 50,
                    "included_positions": ["MID"],
                    "excluded_positions": [],
                    "included_clubs": [],
                    "excluded_clubs": [],
                    "favorite_clubs": ["Arsenal"],
                    "favorite_player_ids": [str(favorite_player_id)],
                    "min_current_price": "0.0000",
                    "max_current_price": None,
                    "require_active_instrument": True,
                },
                "randomness": {
                    "random_alpha_min": -0.4,
                    "random_alpha_max": 0.4,
                    "buy_bias": 0.08,
                    "sell_bias": 0.0,
                    "favorite_club_bias": 0.12,
                    "recognizable_player_bias": 0.1,
                    "recent_mover_bias": 0.08,
                    "holding_bias": 0.05,
                },
                "signal_weights": {
                    "random_component": 0.55,
                    "popularity_bias": 0.15,
                    "recent_mover_bias": 0.1,
                    "favorite_bias": 0.1,
                    "holding_bias": 0.05,
                    "cash_pressure": 0.05,
                    "volatility_risk": -0.05,
                },
                "decision": {
                    "buy_threshold": 0.25,
                    "sell_threshold": -0.3,
                    "min_confidence": 0.2,
                    "hold_band": 0.15,
                    "allow_sells": True,
                    "sell_only_if_position_exists": True,
                },
                "risk": {
                    "max_trade_cash_pct": 0.015,
                    "min_trade_cash_amount": "10.0000",
                    "max_trade_cash_amount": "500.0000",
                    "max_player_position_pct": 0.08,
                    "max_team_exposure_pct": 0.2,
                    "min_cash_reserve_pct": 0.05,
                    "max_daily_trades": 8,
                    "max_daily_turnover_pct": 0.15,
                    "volatility_tolerance": 0.8,
                },
                "sizing": {
                    "base_cash_pct": 0.008,
                    "confidence_multiplier": 0.5,
                    "random_size_multiplier_min": 0.5,
                    "random_size_multiplier_max": 1.5,
                    "position_concentration_penalty": 0.7,
                },
                "execution": {
                    "tick_cadence_minutes": 60,
                    "cooldown_minutes": 120,
                    "decision_jitter_minutes": 30,
                    "trade_probability": 0.25,
                    "size_noise_pct": 0.35,
                    "max_orders_per_tick": 1,
                },
            },
        )

        self.assertIsInstance(config, NoiseConfig)
        self.assertEqual(config.universe.favorite_player_ids, (favorite_player_id,))
        self.assertEqual(config.randomness.activity_floor_minutes, 60)
        self.assertEqual(config.randomness.activity_floor_weight, 0.0)
        self.assertFalse(config.explainability.enabled)

    def test_parse_market_momentum_config(self) -> None:
        config = parse_strategy_config(StrategyEngine.MARKET_MOMENTUM, _market_momentum_payload())

        self.assertIsInstance(config, MarketMomentumConfig)
        self.assertEqual(config.lookbacks.breakout_window_days, 14)
        self.assertEqual(config.execution.max_orders_per_tick, 2)

    def test_parse_stats_value_config(self) -> None:
        config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())

        self.assertIsInstance(config, StatsValueConfig)
        self.assertAlmostEqual(config.valuation.fair_value_blend.performance_implied_value, 0.45)
        self.assertTrue(config.decision.allow_sells)

    def test_parse_social_sentiment_config(self) -> None:
        config = parse_strategy_config(StrategyEngine.SOCIAL_SENTIMENT, _social_payload())

        self.assertIsInstance(config, SocialSentimentConfig)
        self.assertFalse(config.social_inputs.contrarian_mode)
        self.assertEqual(config.lookbacks.news_window_hours, 24)

    def test_parse_portfolio_rebalancer_config(self) -> None:
        config = parse_strategy_config(
            StrategyEngine.PORTFOLIO_REBALANCER,
            _portfolio_payload(),
        )

        self.assertIsInstance(config, PortfolioRebalancerConfig)
        self.assertAlmostEqual(config.portfolio_targets.target_cash_pct, 0.15)
        self.assertEqual(config.risk.max_daily_trades, 12)

    def test_parse_betting_market_value_config(self) -> None:
        config = parse_strategy_config(
            StrategyEngine.BETTING_MARKET_VALUE,
            _betting_market_payload(),
        )

        self.assertIsInstance(config, BettingMarketValueConfig)
        self.assertEqual(config.lookbacks.max_quote_age_minutes, 20)
        self.assertEqual(config.betting_inputs.min_distinct_market_types, 2)

    def test_betting_market_config_rejects_unknown_market_type(self) -> None:
        payload = _betting_market_payload()
        payload["betting_inputs"]["market_type_weights"]["PLAYER_HEIGHT"] = 0.1

        with self.assertRaises(SyntheticTraderConfigError):
            parse_strategy_config(StrategyEngine.BETTING_MARKET_VALUE, payload)

    def test_betting_market_config_rejects_unreachable_market_coverage(self) -> None:
        payload = _betting_market_payload()
        payload["betting_inputs"]["min_distinct_market_types"] = 4

        with self.assertRaises(SyntheticTraderConfigError):
            parse_strategy_config(StrategyEngine.BETTING_MARKET_VALUE, payload)

    def test_invalid_execution_probability_raises(self) -> None:
        payload = _market_momentum_payload()
        payload["execution"]["trade_probability"] = 1.5

        with self.assertRaises(SyntheticTraderConfigError):
            parse_strategy_config(StrategyEngine.MARKET_MOMENTUM, payload)


def _market_momentum_payload() -> dict[str, object]:
    return {
        "universe": {
            "max_candidates": 120,
            "included_positions": ["FWD", "MID", "DEF", "GK"],
            "excluded_positions": [],
            "included_clubs": [],
            "excluded_clubs": [],
            "min_current_price": "0.0000",
            "max_current_price": None,
            "min_recent_trades": 3,
            "min_recent_volume_cash": "250.0000",
            "require_active_instrument": True,
        },
        "lookbacks": {
            "price_momentum_minutes": 240,
            "volume_window_minutes": 240,
            "buy_sell_pressure_minutes": 120,
            "volatility_window_days": 7,
            "breakout_window_days": 14,
        },
        "signal_weights": {
            "price_momentum": 0.3,
            "buy_sell_pressure": 0.25,
            "volume_confirmation": 0.2,
            "breakout_strength": 0.15,
            "unique_trader_participation": 0.1,
            "stats_confirmation": 0.05,
            "crowded_trade": -0.2,
            "volatility_risk": -0.15,
        },
        "market_inputs": {
            "min_price_move_pct": 0.03,
            "breakout_near_high_pct": 0.02,
            "buy_pressure_threshold": 0.6,
            "crowded_unique_buyer_threshold": 20,
            "allow_chasing_new_highs": True,
            "allow_fading_failed_breakouts": False,
        },
        "decision": {
            "buy_threshold": 0.6,
            "sell_threshold": -0.5,
            "min_confidence": 0.55,
            "hold_band": 0.08,
            "allow_sells": True,
            "sell_only_if_position_exists": True,
        },
        "risk": {
            "max_trade_cash_pct": 0.04,
            "min_trade_cash_amount": "25.0000",
            "max_trade_cash_amount": "1800.0000",
            "max_player_position_pct": 0.12,
            "max_team_exposure_pct": 0.25,
            "min_cash_reserve_pct": 0.08,
            "max_daily_trades": 18,
            "max_daily_turnover_pct": 0.4,
            "volatility_tolerance": 0.7,
            "reduce_size_when_confidence_below": 0.7,
        },
        "sizing": {
            "base_cash_pct": 0.02,
            "confidence_multiplier": 1.1,
            "momentum_multiplier": 1.2,
            "volume_multiplier": 0.8,
            "volatility_size_penalty": 0.7,
            "position_concentration_penalty": 0.8,
        },
        "execution": {
            "tick_cadence_minutes": 30,
            "cooldown_minutes": 90,
            "decision_jitter_minutes": 10,
            "trade_probability": 0.45,
            "size_noise_pct": 0.2,
            "max_orders_per_tick": 2,
        },
    }


def _stats_value_payload() -> dict[str, object]:
    return {
        "universe": {
            "max_candidates": 80,
            "included_positions": ["FWD", "MID", "DEF", "GK"],
            "excluded_positions": [],
            "included_clubs": [],
            "excluded_clubs": [],
            "min_current_price": "0.0000",
            "max_current_price": None,
            "require_active_instrument": True,
        },
        "lookbacks": {
            "form_matches": 5,
            "baseline_matches": 20,
            "minutes_matches": 8,
            "market_value_days": 180,
            "price_momentum_days": 7,
        },
        "signal_weights": {
            "stats_form": 0.3,
            "minutes_security": 0.2,
            "market_value_gap": 0.2,
            "fixture_context": 0.1,
            "position_adjustment": 0.1,
            "stockball_price_momentum": 0.05,
            "social_confirmation": 0.05,
            "availability_risk": -0.25,
            "volatility_risk": -0.1,
        },
        "stats_inputs": {
            "rating_weight": 0.35,
            "goals_weight": 0.2,
            "assists_weight": 0.15,
            "clean_sheet_weight": 0.08,
            "defensive_actions_weight": 0.08,
            "shots_weight": 0.06,
            "key_passes_weight": 0.05,
            "cards_penalty_weight": -0.08,
            "position_baseline_enabled": True,
        },
        "valuation": {
            "fair_value_blend": {
                "performance_implied_value": 0.45,
                "market_value_observation": 0.35,
                "current_stockball_price": 0.2,
            },
            "min_valuation_gap_to_buy": 0.08,
            "min_overvaluation_gap_to_sell": 0.12,
            "cap_extreme_gap_at": 0.75,
        },
        "decision": {
            "buy_threshold": 0.62,
            "sell_threshold": -0.45,
            "min_confidence": 0.6,
            "hold_band": 0.08,
            "allow_sells": True,
            "sell_only_if_position_exists": True,
        },
        "risk": {
            "max_trade_cash_pct": 0.05,
            "min_trade_cash_amount": "50.0000",
            "max_trade_cash_amount": "2500.0000",
            "max_player_position_pct": 0.15,
            "max_team_exposure_pct": 0.3,
            "min_cash_reserve_pct": 0.1,
            "max_daily_trades": 10,
            "max_daily_turnover_pct": 0.25,
            "volatility_tolerance": 0.45,
            "reduce_size_when_confidence_below": 0.75,
        },
        "sizing": {
            "base_cash_pct": 0.025,
            "confidence_multiplier": 1.2,
            "expected_return_multiplier": 0.8,
            "volatility_size_penalty": 0.6,
            "position_concentration_penalty": 0.7,
        },
        "execution": {
            "tick_cadence_minutes": 60,
            "cooldown_minutes": 180,
            "decision_jitter_minutes": 20,
            "trade_probability": 0.35,
            "size_noise_pct": 0.15,
            "max_orders_per_tick": 1,
        },
    }


def _social_payload() -> dict[str, object]:
    return {
        "universe": {
            "max_candidates": 100,
            "included_positions": ["FWD", "MID", "DEF", "GK"],
            "excluded_positions": [],
            "included_clubs": [],
            "excluded_clubs": [],
            "min_current_price": "0.0000",
            "max_current_price": None,
            "require_active_instrument": True,
        },
        "lookbacks": {
            "mention_window_minutes": 180,
            "baseline_window_days": 14,
            "news_window_hours": 24,
            "price_momentum_hours": 24,
            "sentiment_window_hours": 24,
        },
        "signal_weights": {
            "mention_spike": 0.3,
            "mention_velocity": 0.2,
            "sentiment": 0.2,
            "news_velocity": 0.15,
            "source_credibility": 0.1,
            "stockball_price_momentum": 0.1,
            "stats_confirmation": 0.05,
            "hype_overextension": -0.25,
            "negative_news_risk": -0.35,
        },
        "social_inputs": {
            "min_mentions": 10,
            "mention_spike_zscore_to_trade": 1.5,
            "positive_sentiment_threshold": 0.2,
            "negative_sentiment_threshold": -0.2,
            "trusted_source_multiplier": 1.25,
            "untrusted_source_multiplier": 0.5,
            "contrarian_mode": False,
        },
        "decision": {
            "buy_threshold": 0.58,
            "sell_threshold": -0.5,
            "min_confidence": 0.55,
            "hold_band": 0.1,
            "allow_sells": True,
            "sell_only_if_position_exists": True,
        },
        "risk": {
            "max_trade_cash_pct": 0.04,
            "min_trade_cash_amount": "25.0000",
            "max_trade_cash_amount": "2000.0000",
            "max_player_position_pct": 0.12,
            "max_team_exposure_pct": 0.28,
            "min_cash_reserve_pct": 0.08,
            "max_daily_trades": 16,
            "max_daily_turnover_pct": 0.35,
            "volatility_tolerance": 0.65,
            "reduce_size_when_confidence_below": 0.7,
        },
        "sizing": {
            "base_cash_pct": 0.02,
            "confidence_multiplier": 1.1,
            "hype_multiplier": 1.25,
            "sentiment_multiplier": 0.8,
            "overextension_size_penalty": 0.7,
            "position_concentration_penalty": 0.8,
        },
        "execution": {
            "tick_cadence_minutes": 30,
            "cooldown_minutes": 90,
            "decision_jitter_minutes": 15,
            "trade_probability": 0.45,
            "size_noise_pct": 0.25,
            "max_orders_per_tick": 1,
        },
    }


def _portfolio_payload() -> dict[str, object]:
    return {
        "portfolio_targets": {
            "target_cash_pct": 0.15,
            "min_cash_pct": 0.08,
            "max_cash_pct": 0.35,
            "max_player_position_pct": 0.12,
            "max_team_exposure_pct": 0.25,
            "max_position_count": 30,
            "min_position_cash_value": "25.0000",
        },
        "rebalance_rules": {
            "cash_deploy_threshold_pct": 0.08,
            "cash_raise_threshold_pct": 0.08,
            "player_overweight_threshold_pct": 0.03,
            "team_overweight_threshold_pct": 0.05,
            "trim_to_target_pct": 0.5,
            "profit_take_return_pct": 0.25,
            "loss_reduce_return_pct": -0.2,
            "allow_new_positions": True,
            "allow_full_exit": False,
        },
        "candidate_selection": {
            "max_buy_candidates": 50,
            "max_sell_candidates": 50,
            "prefer_existing_watchlist": True,
            "prefer_positive_alpha_when_deploying_cash": True,
            "avoid_frozen_or_inactive_instruments": True,
        },
        "signal_weights": {
            "portfolio_drift": 0.45,
            "cash_drift": 0.25,
            "concentration_risk": 0.2,
            "profit_taking": 0.15,
            "positive_alpha_tiebreaker": 0.1,
            "volatility_risk": -0.15,
        },
        "decision": {
            "rebalance_threshold": 0.12,
            "min_confidence": 0.5,
            "allow_buys": True,
            "allow_sells": True,
            "sell_only_if_position_exists": True,
        },
        "risk": {
            "max_trade_cash_pct": 0.035,
            "min_trade_cash_amount": "25.0000",
            "max_trade_cash_amount": "1500.0000",
            "max_daily_trades": 12,
            "max_daily_turnover_pct": 0.25,
            "volatility_tolerance": 0.5,
        },
        "sizing": {
            "base_rebalance_pct": 0.4,
            "cash_drift_multiplier": 0.8,
            "concentration_multiplier": 1.0,
            "profit_take_multiplier": 0.5,
            "volatility_size_penalty": 0.5,
        },
        "execution": {
            "tick_cadence_minutes": 180,
            "cooldown_minutes": 360,
            "decision_jitter_minutes": 30,
            "trade_probability": 0.4,
            "size_noise_pct": 0.1,
            "max_orders_per_tick": 3,
        },
    }


def _betting_market_payload() -> dict[str, object]:
    return {
        "universe": {
            "max_candidates": 100,
            "included_positions": ["FWD", "MID", "DEF", "GK"],
            "excluded_positions": [],
            "included_clubs": [],
            "excluded_clubs": [],
            "min_current_price": "0.0000",
            "max_current_price": None,
            "require_active_instrument": True,
        },
        "lookbacks": {
            "movement_minutes": 60,
            "max_quote_age_minutes": 20,
        },
        "signal_weights": {
            "implied_probability_rank": 0.55,
            "probability_movement": 0.3,
            "cross_market_confirmation": 0.15,
        },
        "betting_inputs": {
            "min_distinct_market_types": 2,
            "min_observations_per_selection": 2,
            "min_implied_probability": 0.05,
            "movement_scale": 0.25,
            "market_type_weights": {
                "GOALSCORER": 0.35,
                "SCORE_OR_ASSIST": 0.35,
                "SHOTS_ON_TARGET": 0.3,
            },
        },
        "decision": {
            "buy_threshold": 0.5,
            "sell_threshold": -0.5,
            "min_confidence": 0.6,
            "hold_band": 0.1,
            "allow_sells": True,
            "sell_only_if_position_exists": True,
        },
        "risk": {
            "max_trade_cash_pct": 0.025,
            "min_trade_cash_amount": "25.0000",
            "max_trade_cash_amount": "1000.0000",
            "max_player_position_pct": 0.1,
            "max_team_exposure_pct": 0.25,
            "min_cash_reserve_pct": 0.12,
            "max_daily_trades": 8,
            "max_daily_turnover_pct": 0.2,
            "volatility_tolerance": 0.5,
            "reduce_size_when_confidence_below": 0.7,
        },
        "sizing": {
            "base_cash_pct": 0.015,
            "confidence_multiplier": 0.8,
            "movement_multiplier": 0.5,
            "position_concentration_penalty": 0.8,
        },
        "execution": {
            "tick_cadence_minutes": 10,
            "cooldown_minutes": 45,
            "decision_jitter_minutes": 5,
            "trade_probability": 0.3,
            "size_noise_pct": 0.1,
            "max_orders_per_tick": 1,
        },
    }


if __name__ == "__main__":
    unittest.main()
