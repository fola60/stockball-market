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
            'BETTING_MARKET_VALUE'
        )
    );

INSERT INTO synthetic_trader_bot_configs (
    config_key,
    display_name,
    strategy_engine,
    version,
    config
) VALUES
(
    'BETTING_MARKET_CONSERVATIVE',
    'Betting Market Conservative',
    'BETTING_MARKET_VALUE',
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
        "movement_minutes": 60,
        "max_quote_age_minutes": 20
      },
      "signal_weights": {
        "implied_probability_rank": 0.55,
        "probability_movement": 0.30,
        "cross_market_confirmation": 0.15
      },
      "betting_inputs": {
        "min_distinct_market_types": 3,
        "min_observations_per_selection": 2,
        "min_implied_probability": 0.05,
        "movement_scale": 0.25,
        "market_type_weights": {
          "GOALSCORER": 0.30,
          "ASSIST": 0.20,
          "SCORE_OR_ASSIST": 0.25,
          "SHOTS": 0.10,
          "SHOTS_ON_TARGET": 0.15
        }
      },
      "decision": {
        "buy_threshold": 0.55,
        "sell_threshold": -0.55,
        "min_confidence": 0.65,
        "hold_band": 0.10,
        "allow_sells": true,
        "sell_only_if_position_exists": true
      },
      "risk": {
        "max_trade_cash_pct": 0.025,
        "min_trade_cash_amount": "25.0000",
        "max_trade_cash_amount": "1000.0000",
        "max_player_position_pct": 0.10,
        "max_team_exposure_pct": 0.25,
        "min_cash_reserve_pct": 0.12,
        "max_daily_trades": 8,
        "max_daily_turnover_pct": 0.20,
        "volatility_tolerance": 0.50,
        "reduce_size_when_confidence_below": 0.70
      },
      "sizing": {
        "base_cash_pct": 0.015,
        "confidence_multiplier": 0.80,
        "movement_multiplier": 0.50,
        "position_concentration_penalty": 0.80
      },
      "execution": {
        "tick_cadence_minutes": 10,
        "cooldown_minutes": 45,
        "decision_jitter_minutes": 5,
        "trade_probability": 0.30,
        "size_noise_pct": 0.10,
        "max_orders_per_tick": 1
      },
      "explainability": {
        "enabled": false,
        "record_top_signal_count": 0,
        "include_raw_component_scores": false
      }
    }$$::jsonb
),
(
    'BETTING_MARKET_AGGRESSIVE',
    'Betting Market Aggressive',
    'BETTING_MARKET_VALUE',
    1,
    $${
      "universe": {
        "max_candidates": 160,
        "included_positions": ["FWD", "MID", "DEF", "GK"],
        "excluded_positions": [],
        "included_clubs": [],
        "excluded_clubs": [],
        "min_current_price": "0.0000",
        "max_current_price": null,
        "require_active_instrument": true
      },
      "lookbacks": {
        "movement_minutes": 20,
        "max_quote_age_minutes": 10
      },
      "signal_weights": {
        "implied_probability_rank": 0.40,
        "probability_movement": 0.45,
        "cross_market_confirmation": 0.15
      },
      "betting_inputs": {
        "min_distinct_market_types": 2,
        "min_observations_per_selection": 1,
        "min_implied_probability": 0.03,
        "movement_scale": 0.15,
        "market_type_weights": {
          "GOALSCORER": 0.30,
          "ASSIST": 0.15,
          "SCORE_OR_ASSIST": 0.25,
          "SHOTS": 0.10,
          "SHOTS_ON_TARGET": 0.20
        }
      },
      "decision": {
        "buy_threshold": 0.30,
        "sell_threshold": -0.30,
        "min_confidence": 0.45,
        "hold_band": 0.05,
        "allow_sells": true,
        "sell_only_if_position_exists": true
      },
      "risk": {
        "max_trade_cash_pct": 0.05,
        "min_trade_cash_amount": "25.0000",
        "max_trade_cash_amount": "2500.0000",
        "max_player_position_pct": 0.15,
        "max_team_exposure_pct": 0.30,
        "min_cash_reserve_pct": 0.08,
        "max_daily_trades": 20,
        "max_daily_turnover_pct": 0.50,
        "volatility_tolerance": 0.75,
        "reduce_size_when_confidence_below": 0.55
      },
      "sizing": {
        "base_cash_pct": 0.03,
        "confidence_multiplier": 1.20,
        "movement_multiplier": 1.00,
        "position_concentration_penalty": 0.65
      },
      "execution": {
        "tick_cadence_minutes": 3,
        "cooldown_minutes": 15,
        "decision_jitter_minutes": 2,
        "trade_probability": 0.60,
        "size_noise_pct": 0.20,
        "max_orders_per_tick": 2
      },
      "explainability": {
        "enabled": false,
        "record_top_signal_count": 0,
        "include_raw_component_scores": false
      }
    }$$::jsonb
)
ON CONFLICT (config_key) DO NOTHING;
