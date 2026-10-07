-- FotMob match ratings reach synthetic traders (behind STOCKBALL_MATCH_RATING_SIGNALS_ENABLED).

ALTER TABLE synthetic_trader_bot_configs
    DROP CONSTRAINT IF EXISTS synthetic_trader_bot_configs_strategy_engine_check;
ALTER TABLE synthetic_trader_bot_configs
    ADD CONSTRAINT synthetic_trader_bot_configs_strategy_engine_check
    CHECK (
        strategy_engine IN (
            'NOISE',
            'MARKET_MOMENTUM',
            'STATS_VALUE',
            'SOCIAL_SENTIMENT',
            'PORTFOLIO_REBALANCER',
            'BETTING_MARKET_VALUE',
            'EVENT_REACTION'
        )
    );

-- The general stats profiles seeded a 0.35 rating weight that never applied. Ratings now arrive
-- as a league percentile and also drive rating form, so they take a smaller share there; the
-- ratings-led profile below carries the heavy weight. Spawned bots hold a randomized copy of
-- the old weight, so scale theirs by the same factor to keep each bot's own variation.
UPDATE synthetic_trader_bots AS bot
SET config_overrides = jsonb_set(
        bot.config_overrides,
        '{stats_inputs,rating_weight}',
        to_jsonb(round((bot.config_overrides #>> '{stats_inputs,rating_weight}')::numeric
            * 0.2 / 0.35, 6))
    ),
    updated_at = now()
FROM synthetic_trader_bot_configs AS profile
WHERE bot.config_id = profile.id
  AND profile.config_key IN ('STATS_VALUE_CONSERVATIVE', 'STATS_VALUE_AGGRESSIVE')
  AND (profile.config #>> '{stats_inputs,rating_weight}')::numeric = 0.35
  AND jsonb_typeof(bot.config_overrides #> '{stats_inputs,rating_weight}') = 'number';

UPDATE synthetic_trader_bot_configs
SET config = jsonb_set(config, '{stats_inputs,rating_weight}', '0.2'),
    version = version + 1, updated_at = now()
WHERE config_key IN ('STATS_VALUE_CONSERVATIVE', 'STATS_VALUE_AGGRESSIVE')
  AND (config #>> '{stats_inputs,rating_weight}')::numeric = 0.35;

INSERT INTO synthetic_trader_bot_configs (
    config_key,
    display_name,
    strategy_engine,
    version,
    config
) VALUES
(
    'STATS_VALUE_RATINGS',
    'Ratings Value Investor',
    'STATS_VALUE',
    1,
    $${
      "universe": {
        "max_candidates": 90,
        "included_positions": ["FWD", "MID", "DEF", "GK"],
        "excluded_positions": [],
        "included_clubs": [],
        "excluded_clubs": [],
        "min_current_price": "0.0000",
        "max_current_price": null,
        "require_active_instrument": true
      },
      "lookbacks": {
        "form_matches": 6,
        "market_value_days": 180,
        "price_momentum_days": 7
      },
      "signal_weights": {
        "stats_form": 0.38,
        "minutes_security": 0.18,
        "market_value_gap": 0.2,
        "fixture_context": 0.06,
        "position_adjustment": 0.08,
        "stockball_price_momentum": 0.02,
        "social_confirmation": 0.02,
        "availability_risk": -0.25,
        "volatility_risk": -0.1
      },
      "stats_inputs": {
        "rating_weight": 0.9,
        "goals_weight": 0.08,
        "assists_weight": 0.06,
        "clean_sheet_weight": 0.04,
        "defensive_actions_weight": 0.05,
        "shots_weight": 0.03,
        "key_passes_weight": 0.03,
        "cards_penalty_weight": -0.05,
        "minutes_weight": 0.12,
        "form_weight": 0.08,
        "position_baseline_enabled": true
      },
      "valuation": {
        "fair_value_blend": {
          "performance_implied_value": 0.55,
          "market_value_observation": 0.25,
          "current_stockball_price": 0.2
        },
        "min_valuation_gap_to_buy": 0.08,
        "min_overvaluation_gap_to_sell": 0.12,
        "cap_extreme_gap_at": 0.75
      },
      "decision": {
        "buy_threshold": 0.58,
        "sell_threshold": -0.42,
        "min_confidence": 0.55,
        "hold_band": 0.08,
        "allow_sells": true
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
        "reduce_size_when_confidence_below": 0.7
      },
      "sizing": {
        "base_cash_pct": 0.025,
        "confidence_multiplier": 1.2,
        "expected_return_multiplier": 0.8,
        "volatility_size_penalty": 0.6,
        "position_concentration_penalty": 0.7
      },
      "execution": {
        "tick_cadence_minutes": 60,
        "cooldown_minutes": 180,
        "decision_jitter_minutes": 20,
        "trade_probability": 0.35,
        "size_noise_pct": 0.15,
        "max_orders_per_tick": 1
      },
      "explainability": {
        "enabled": true,
        "record_top_signal_count": 5,
        "include_raw_component_scores": true
      }
    }$$::jsonb
),
(
    'STATS_VALUE_FORM_CHASER',
    'Form Chaser',
    'STATS_VALUE',
    1,
    $${
      "universe": {
        "max_candidates": 90,
        "included_positions": ["FWD", "MID", "DEF", "GK"],
        "excluded_positions": [],
        "included_clubs": [],
        "excluded_clubs": [],
        "min_current_price": "0.0000",
        "max_current_price": null,
        "require_active_instrument": true
      },
      "lookbacks": {
        "form_matches": 4,
        "market_value_days": 180,
        "price_momentum_days": 3
      },
      "signal_weights": {
        "stats_form": 0.42,
        "minutes_security": 0.1,
        "market_value_gap": 0.1,
        "fixture_context": 0.12,
        "position_adjustment": 0.05,
        "stockball_price_momentum": 0.1,
        "social_confirmation": 0.05,
        "availability_risk": -0.2,
        "volatility_risk": -0.06
      },
      "stats_inputs": {
        "rating_weight": 0.2,
        "goals_weight": 0.12,
        "assists_weight": 0.08,
        "clean_sheet_weight": 0.04,
        "defensive_actions_weight": 0.06,
        "shots_weight": 0.05,
        "key_passes_weight": 0.04,
        "cards_penalty_weight": -0.06,
        "minutes_weight": 0.08,
        "form_weight": 0.7,
        "position_baseline_enabled": true
      },
      "valuation": {
        "fair_value_blend": {
          "performance_implied_value": 0.6,
          "market_value_observation": 0.2,
          "current_stockball_price": 0.2
        },
        "min_valuation_gap_to_buy": 0.05,
        "min_overvaluation_gap_to_sell": 0.08,
        "cap_extreme_gap_at": 0.75
      },
      "decision": {
        "buy_threshold": 0.5,
        "sell_threshold": -0.3,
        "min_confidence": 0.45,
        "hold_band": 0.06,
        "allow_sells": true
      },
      "risk": {
        "max_trade_cash_pct": 0.05,
        "min_trade_cash_amount": "25.0000",
        "max_trade_cash_amount": "2000.0000",
        "max_player_position_pct": 0.14,
        "max_team_exposure_pct": 0.3,
        "min_cash_reserve_pct": 0.08,
        "max_daily_trades": 12,
        "max_daily_turnover_pct": 0.35,
        "volatility_tolerance": 0.65,
        "reduce_size_when_confidence_below": 0.6
      },
      "sizing": {
        "base_cash_pct": 0.025,
        "confidence_multiplier": 1.0,
        "expected_return_multiplier": 0.9,
        "volatility_size_penalty": 0.45,
        "position_concentration_penalty": 0.65
      },
      "execution": {
        "tick_cadence_minutes": 30,
        "cooldown_minutes": 90,
        "decision_jitter_minutes": 15,
        "trade_probability": 0.45,
        "size_noise_pct": 0.2,
        "max_orders_per_tick": 1
      },
      "explainability": {
        "enabled": true,
        "record_top_signal_count": 5,
        "include_raw_component_scores": true
      }
    }$$::jsonb
),
(
    'EVENT_REACTION_MEASURED',
    'Measured Post-Match Reactor',
    'EVENT_REACTION',
    1,
    $${
      "universe": {
        "max_candidates": 120,
        "included_positions": ["FWD", "MID", "DEF", "GK"],
        "excluded_positions": [],
        "included_clubs": [],
        "excluded_clubs": [],
        "min_current_price": "0.0000",
        "max_current_price": null,
        "require_active_instrument": true
      },
      "lookbacks": {
        "event_window_hours": 48,
        "betting_movement_minutes": 720
      },
      "signal_weights": {
        "match_surprise": 0.7,
        "next_match_odds_movement": 0.25,
        "price_already_moved": -0.35,
        "season_quality": 0.05
      },
      "event_inputs": {
        "min_minutes": 60,
        "surprise_scale": 2.0,
        "expectation_weight": 0.5,
        "half_life_hours": 18,
        "reaction_delay_minutes": 120,
        "holding_period_hours": 30,
        "priced_in_move_pct": 0.08,
        "movement_scale": 0.25,
        "market_type_weights": {
          "SCORE_OR_ASSIST": 0.35,
          "GOALSCORER": 0.25,
          "ASSIST": 0.15,
          "SHOTS_ON_TARGET": 0.15,
          "SHOTS": 0.10
        },
        "unwind_fraction": 0.5
      },
      "decision": {
        "buy_threshold": 0.35,
        "sell_threshold": -0.3,
        "min_confidence": 0.6,
        "hold_band": 0.08,
        "allow_sells": true
      },
      "risk": {
        "max_trade_cash_pct": 0.04,
        "min_trade_cash_amount": "25.0000",
        "max_trade_cash_amount": "2000.0000",
        "max_player_position_pct": 0.1,
        "max_team_exposure_pct": 0.25,
        "min_cash_reserve_pct": 0.1,
        "max_daily_trades": 8,
        "max_daily_turnover_pct": 0.3,
        "volatility_tolerance": 0.6
      },
      "sizing": {
        "base_cash_pct": 0.02,
        "confidence_multiplier": 1.0,
        "surprise_multiplier": 0.8,
        "position_concentration_penalty": 0.6
      },
      "execution": {
        "tick_cadence_minutes": 30,
        "cooldown_minutes": 60,
        "decision_jitter_minutes": 15,
        "trade_probability": 0.6,
        "size_noise_pct": 0.2,
        "max_orders_per_tick": 1
      },
      "explainability": {
        "enabled": true,
        "record_top_signal_count": 5,
        "include_raw_component_scores": true
      }
    }$$::jsonb
),
(
    'EVENT_REACTION_FAST',
    'Fast Post-Match Reactor',
    'EVENT_REACTION',
    1,
    $${
      "universe": {
        "max_candidates": 120,
        "included_positions": ["FWD", "MID", "DEF", "GK"],
        "excluded_positions": [],
        "included_clubs": [],
        "excluded_clubs": [],
        "min_current_price": "0.0000",
        "max_current_price": null,
        "require_active_instrument": true
      },
      "lookbacks": {
        "event_window_hours": 36,
        "betting_movement_minutes": 360
      },
      "signal_weights": {
        "match_surprise": 0.85,
        "next_match_odds_movement": 0.1,
        "price_already_moved": -0.15
      },
      "event_inputs": {
        "min_minutes": 45,
        "surprise_scale": 1.6,
        "expectation_weight": 0.25,
        "half_life_hours": 8,
        "reaction_delay_minutes": 20,
        "holding_period_hours": 14,
        "priced_in_move_pct": 0.12,
        "movement_scale": 0.25,
        "market_type_weights": {
          "SCORE_OR_ASSIST": 0.35,
          "GOALSCORER": 0.25,
          "ASSIST": 0.15,
          "SHOTS_ON_TARGET": 0.15,
          "SHOTS": 0.10
        },
        "unwind_fraction": 1.0
      },
      "decision": {
        "buy_threshold": 0.3,
        "sell_threshold": -0.25,
        "min_confidence": 0.4,
        "hold_band": 0.05,
        "allow_sells": true
      },
      "risk": {
        "max_trade_cash_pct": 0.03,
        "min_trade_cash_amount": "10.0000",
        "max_trade_cash_amount": "1000.0000",
        "max_player_position_pct": 0.08,
        "max_team_exposure_pct": 0.2,
        "min_cash_reserve_pct": 0.05,
        "max_daily_trades": 12,
        "max_daily_turnover_pct": 0.4,
        "volatility_tolerance": 0.8
      },
      "sizing": {
        "base_cash_pct": 0.015,
        "confidence_multiplier": 0.6,
        "surprise_multiplier": 1.0,
        "position_concentration_penalty": 0.7
      },
      "execution": {
        "tick_cadence_minutes": 15,
        "cooldown_minutes": 30,
        "decision_jitter_minutes": 10,
        "trade_probability": 0.55,
        "size_noise_pct": 0.35,
        "max_orders_per_tick": 2
      },
      "explainability": {
        "enabled": true,
        "record_top_signal_count": 5,
        "include_raw_component_scores": true
      }
    }$$::jsonb
);
