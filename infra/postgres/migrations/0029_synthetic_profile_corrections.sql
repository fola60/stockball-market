-- Profile v2: enable recent form for existing bots without replacing explicit personal choices.
UPDATE synthetic_trader_bot_configs
SET config = jsonb_set(config, '{stats_inputs}',
        '{"minutes_weight":0.15,"form_weight":0.1}'::jsonb || COALESCE(config->'stats_inputs', '{}')),
    version = version + 1, updated_at = now()
WHERE strategy_engine = 'STATS_VALUE';

-- The contrarian now has explicit recovery and fade signals; retain the existing risk limits.
UPDATE synthetic_trader_bot_configs
SET config = jsonb_set(config, '{signal_weights}',
    '{"pessimism_recovery":1.0,"hype_fade":1.0,"hype_overextension":-0.35}'),
    version = version + 1, updated_at = now()
WHERE config_key = 'SOCIAL_CONTRARIAN';

-- Movement needs two observations. This is also enforced by the engine for old overrides.
UPDATE synthetic_trader_bot_configs
SET config = jsonb_set(config, '{betting_inputs,min_observations_per_selection}', '2'),
    version = version + 1, updated_at = now()
WHERE strategy_engine = 'BETTING_MARKET_VALUE'
  AND (config #>> '{betting_inputs,min_observations_per_selection}')::int < 2;

-- Remove retired controls from stored profiles and per-bot overrides. Parsers tolerate legacy JSON.
UPDATE synthetic_trader_bot_configs
SET config = config #- '{lookbacks,baseline_matches}' #- '{lookbacks,minutes_matches}'
    #- '{lookbacks,mention_window_minutes}' #- '{lookbacks,baseline_window_days}'
    #- '{lookbacks,news_window_hours}' #- '{lookbacks,sentiment_window_hours}'
    #- '{decision,rebalance_threshold}' #- '{decision,sell_only_if_position_exists}',
    updated_at = now();
UPDATE synthetic_trader_bots
SET config_overrides = config_overrides #- '{lookbacks,baseline_matches}' #- '{lookbacks,minutes_matches}'
    #- '{lookbacks,mention_window_minutes}' #- '{lookbacks,baseline_window_days}'
    #- '{lookbacks,news_window_hours}' #- '{lookbacks,sentiment_window_hours}'
    #- '{decision,rebalance_threshold}' #- '{decision,sell_only_if_position_exists}',
    updated_at = now();
UPDATE synthetic_trader_bot_configs
SET config = config #- '{decision,min_confidence}'
WHERE strategy_engine = 'PORTFOLIO_REBALANCER';
UPDATE synthetic_trader_bots AS bot
SET config_overrides = bot.config_overrides #- '{decision,min_confidence}'
FROM synthetic_trader_bot_configs AS profile
WHERE bot.config_id = profile.id AND profile.strategy_engine = 'PORTFOLIO_REBALANCER';
UPDATE synthetic_trader_bots AS bot
SET config_overrides = bot.config_overrides
    #- '{signal_weights,mention_spike}' #- '{signal_weights,mention_velocity}'
    #- '{signal_weights,sentiment}' #- '{signal_weights,news_velocity}'
    #- '{signal_weights,source_credibility}' #- '{signal_weights,stockball_price_momentum}'
    #- '{signal_weights,stats_confirmation}' #- '{signal_weights,negative_news_risk}'
FROM synthetic_trader_bot_configs AS profile
WHERE bot.config_id = profile.id AND profile.config_key = 'SOCIAL_CONTRARIAN';
