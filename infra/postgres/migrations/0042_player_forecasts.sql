-- Forecast models and the FORECAST_VALUE trader engine.
--
-- `app.forecasting` in the worker predicts how far a player's FotMob rating over his next
-- matches will land from the steadied season rating the stats bots already price. Models
-- and their daily forecasts are stored here; FORECAST_VALUE bots trade the predicted change
-- (behind STOCKBALL_FORECAST_SIGNALS_ENABLED). No existing profile or bot is changed.

CREATE TABLE IF NOT EXISTS forecast_models (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    signal text NOT NULL CHECK (signal IN ('MATCH_RATING')),
    status text NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED', 'REJECTED')),
    -- Why this model was promoted or turned away when it was trained.
    decision_reason text NOT NULL,
    trained_at timestamptz NOT NULL,
    -- Kickoff of the latest match the model saw.
    trained_through timestamptz,
    training_rows integer NOT NULL CHECK (training_rows >= 0),
    -- {"horizons": {"<matches>": <ridge model>}}
    parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters) = 'object'),
    -- {"<matches>": {skill, baseline_rmse, model_rmse, rank_correlation, usable, ...}}
    evaluation jsonb NOT NULL CHECK (jsonb_typeof(evaluation) = 'object'),
    retired_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS forecast_models_one_active_idx
    ON forecast_models (signal) WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS player_forecasts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id uuid NOT NULL REFERENCES forecast_models (id),
    signal text NOT NULL CHECK (signal IN ('MATCH_RATING')),
    player_id uuid NOT NULL REFERENCES players (id),
    provider_player_id text NOT NULL,
    horizon_matches integer NOT NULL CHECK (horizon_matches > 0),
    forecast_date date NOT NULL,
    as_of timestamptz NOT NULL,
    -- The steadied season rating at `as_of`, and the rating predicted over the horizon.
    baseline numeric(6, 3) NOT NULL,
    predicted numeric(6, 3) NOT NULL,
    expected_change numeric(7, 4) NOT NULL,
    history_nineties numeric(8, 3) NOT NULL CHECK (history_nineties >= 0),
    -- The largest feature contributions to `expected_change`.
    contributions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(contributions) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (signal, player_id, horizon_matches, forecast_date)
);

CREATE INDEX IF NOT EXISTS player_forecasts_latest_idx
    ON player_forecasts (signal, horizon_matches, player_id, as_of DESC);

-- Bookmakers' pre-match result odds for FotMob fixtures, as probabilities with the margin
-- removed. A team's recent odds are the forecast model's measure of how strong it is.
CREATE TABLE IF NOT EXISTS match_result_odds (
    match_id text PRIMARY KEY REFERENCES fotmob_matches (match_id),
    source text NOT NULL,
    home_probability numeric(6, 5) NOT NULL CHECK (home_probability BETWEEN 0 AND 1),
    draw_probability numeric(6, 5) NOT NULL CHECK (draw_probability BETWEEN 0 AND 1),
    away_probability numeric(6, 5) NOT NULL CHECK (away_probability BETWEEN 0 AND 1),
    source_home_team text NOT NULL,
    source_away_team text NOT NULL,
    source_match_date date NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);

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
            'EVENT_REACTION',
            'FORECAST_VALUE'
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
    'FORECAST_NEXT_MATCH',
    'Next Match Forecaster',
    'FORECAST_VALUE',
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
        "price_momentum_days": 3
      },
      "signal_weights": {
        "expected_change": 0.55,
        "change_rank": 0.35,
        "price_already_moved": -0.3,
        "season_quality": 0.1
      },
      "forecast_inputs": {
        "horizon_matches": 1,
        "change_scale": 0.25,
        "max_forecast_age_hours": 96,
        "min_history_nineties": 4,
        "priced_in_move_pct": 0.06
      },
      "decision": {
        "buy_threshold": 0.4,
        "sell_threshold": -0.35,
        "min_confidence": 0.45,
        "hold_band": 0.08,
        "allow_sells": true
      },
      "risk": {
        "max_trade_cash_pct": 0.04,
        "min_trade_cash_amount": "50.0000",
        "max_trade_cash_amount": "2000.0000",
        "max_player_position_pct": 0.1,
        "max_team_exposure_pct": 0.3,
        "min_cash_reserve_pct": 0.1,
        "max_daily_trades": 12,
        "max_daily_turnover_pct": 0.3,
        "volatility_tolerance": 0.5,
        "reduce_size_when_confidence_below": 0.6
      },
      "sizing": {
        "base_cash_pct": 0.015,
        "confidence_multiplier": 1.0,
        "expected_return_multiplier": 1.0,
        "position_concentration_penalty": 0.7
      },
      "execution": {
        "tick_cadence_minutes": 45,
        "cooldown_minutes": 120,
        "decision_jitter_minutes": 15,
        "trade_probability": 0.4,
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
    'FORECAST_FORM_RUN',
    'Form Run Forecaster',
    'FORECAST_VALUE',
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
        "price_momentum_days": 7
      },
      "signal_weights": {
        "expected_change": 0.55,
        "change_rank": 0.35,
        "price_already_moved": -0.25,
        "season_quality": 0.1
      },
      "forecast_inputs": {
        "horizon_matches": 5,
        "change_scale": 0.15,
        "max_forecast_age_hours": 192,
        "min_history_nineties": 4,
        "priced_in_move_pct": 0.1
      },
      "decision": {
        "buy_threshold": 0.4,
        "sell_threshold": -0.35,
        "min_confidence": 0.5,
        "hold_band": 0.08,
        "allow_sells": true
      },
      "risk": {
        "max_trade_cash_pct": 0.05,
        "min_trade_cash_amount": "50.0000",
        "max_trade_cash_amount": "2500.0000",
        "max_player_position_pct": 0.12,
        "max_team_exposure_pct": 0.3,
        "min_cash_reserve_pct": 0.1,
        "max_daily_trades": 8,
        "max_daily_turnover_pct": 0.25,
        "volatility_tolerance": 0.45,
        "reduce_size_when_confidence_below": 0.65
      },
      "sizing": {
        "base_cash_pct": 0.02,
        "confidence_multiplier": 1.1,
        "expected_return_multiplier": 0.9,
        "position_concentration_penalty": 0.7
      },
      "execution": {
        "tick_cadence_minutes": 90,
        "cooldown_minutes": 240,
        "decision_jitter_minutes": 25,
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
    'FORECAST_SEASON_VIEW',
    'Long View Forecaster',
    'FORECAST_VALUE',
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
        "price_momentum_days": 14
      },
      "signal_weights": {
        "expected_change": 0.5,
        "change_rank": 0.35,
        "price_already_moved": -0.2,
        "season_quality": 0.15
      },
      "forecast_inputs": {
        "horizon_matches": 10,
        "change_scale": 0.12,
        "max_forecast_age_hours": 240,
        "min_history_nineties": 6,
        "priced_in_move_pct": 0.15
      },
      "decision": {
        "buy_threshold": 0.42,
        "sell_threshold": -0.38,
        "min_confidence": 0.55,
        "hold_band": 0.1,
        "allow_sells": true
      },
      "risk": {
        "max_trade_cash_pct": 0.06,
        "min_trade_cash_amount": "50.0000",
        "max_trade_cash_amount": "3000.0000",
        "max_player_position_pct": 0.15,
        "max_team_exposure_pct": 0.3,
        "min_cash_reserve_pct": 0.12,
        "max_daily_trades": 5,
        "max_daily_turnover_pct": 0.2,
        "volatility_tolerance": 0.4,
        "reduce_size_when_confidence_below": 0.7
      },
      "sizing": {
        "base_cash_pct": 0.025,
        "confidence_multiplier": 1.2,
        "expected_return_multiplier": 0.8,
        "position_concentration_penalty": 0.7
      },
      "execution": {
        "tick_cadence_minutes": 180,
        "cooldown_minutes": 480,
        "decision_jitter_minutes": 40,
        "trade_probability": 0.3,
        "size_noise_pct": 0.15,
        "max_orders_per_tick": 1
      },
      "explainability": {
        "enabled": true,
        "record_top_signal_count": 5,
        "include_raw_component_scores": true
      }
    }$$::jsonb
)
ON CONFLICT (config_key) DO NOTHING;
