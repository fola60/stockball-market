# Synthetic Trader Strategy Engines

## Purpose

Strategy engines are reusable decision formulas for synthetic traders.

An engine defines how a bot interprets available player, market, fixture, social, betting, and portfolio signals. Individual bot profiles should not require separate code paths. Instead, profiles should point at one engine and provide different config values for weights, thresholds, risk limits, timing, sizing, and trade direction.

```text
engine = formula and decision mechanics
profile config = bot personality and parameter values
```

Signals should influence bot orders only. They must not directly mutate Stockball prices. All bot orders still go through the trading engine.

## Current implementation (October 2026)

The fourteen shipped profiles use seven engines: `NOISE`, `MARKET_MOMENTUM`, `STATS_VALUE`,
`SOCIAL_SENTIMENT`, `PORTFOLIO_REBALANCER`, `BETTING_MARKET_VALUE`, and `EVENT_REACTION`.
Other engine names below are design proposals, not registered implementations.
`FORM_MOMENTUM` ships as the `STATS_VALUE_FORM_CHASER` profile rather than its own engine.

### FotMob match ratings (migration 0032)

Behind `STOCKBALL_MATCH_RATING_SIGNALS_ENABLED` (default off), FotMob final ratings feed
`PlayerStatsContext` through `app.player_stats.ratings`:

- Ratings are weighted by nineties played (cameos rate near 6.3 almost regardless) and
  steadied with a prior worth eight full matches: last season's rating, itself steadied toward
  the league, or the league median. Eight comes from the 2025-26 data: regulars' season
  ratings spread with an SD of 0.28, and one match deviates from a player's norm by 0.77.
- `rating_strength` is the league percentile of that rating. `STATS_VALUE` scores the rating
  by percentile, and `stats_confirmation` averages it with the per-90 percentile. A rating
  never replaces per-90 strength, so players with and without ratings share one scale.
- `rating_form` (last five appearances against the season) joins `form_score`, weighted by
  `rating_weight`. It needs two nineties on each side, so it appears from about round eight.
- Players FotMob rates before FBref lists them are judged on rating alone.
- The general stats profiles' dormant 0.35 `rating_weight` became 0.2. Existing bots'
  randomized copies were scaled by the same factor. `STATS_VALUE_RATINGS` (0.9) is the
  ratings-led profile. Stats-style randomization now centres each bot's draw on its profile's
  mix, so a form chaser's bots keep chasing form.

- Equal signals share a midpoint percentile; a singleton is neutral. Candidate sampling is
  reproducible for each bot and UTC date, reserves capacity for holdings, and includes discovery.
- Trade probability is drawn once per bot tick. Noise activity floors increase participation
  without changing trade direction. Portfolio recovery bypasses that participation gate.
- The worker refreshes portfolio state before each order, obtains a curve quote, and fits the
  quantity to actual cost and post-trade exposure limits. Optional execution limits bind the quote's
  price, cash balance, and maximum gross amount under the trading engine's database locks.
- Recovery consumes only the remaining cash or exposure deficit. A failed sale cannot fund a buy.
- Stats profiles distinguish unavailable data from observed zero, use position peer groups,
  reject snapshots older than 30 days, and default recent-form weight to 0.1. Fixture context
  measures upcoming opportunity and congestion over seven days; it is not opponent difficulty.
- Social aggregation uses shared one-hour current and seven-day baseline windows, scheduled
  every 15 minutes. No baseline means no invented spike and reduced confidence. Per-profile
  social aggregation lookbacks have been retired. Price-momentum lookback remains configurable.
- Contrarians buy pessimism with positive fundamentals and stable prices, fade rising hype,
  and penalize injury risk. Their weights are `pessimism_recovery`, `hype_fade`, and
  `hype_overextension`; migration 0029 updates stored profiles and legacy overrides.
- Rebalancer cash and exposure bands trigger action directly. Profit/loss uses weighted-average
  acquisition cost, including bootstrap allocations. Selling removes proportional cost basis.
- Enabled explainability records the effective configuration and the requested number of
  decisions in job metrics, with raw component scores only when requested.

Migration `0029_synthetic_profile_corrections.sql` supplies defaults and removes retired
controls. Deploy the trading engine first so atomic execution guards are available. Pause the worker,
apply migrations, deploy the updated worker, then resume it; the old parser may still require
retired fields removed by migration 0029. Existing bots retain their
supported personalized overrides; no respawn is necessary.

## Engine Interface

Each engine should produce a comparable decision output:

```text
candidate player/instrument inputs
  -> signal scoring
  -> expected return or alpha score
  -> confidence
  -> buy/sell/hold intent
  -> suggested order size
  -> decision explanation
```

Suggested output fields:

- `side`: `BUY`, `SELL`, or `HOLD`
- `alpha_score`: normalized score, ideally `-1.0` to `1.0`
- `expected_return`: estimated upside/downside from current Stockball price
- `confidence`: normalized confidence, ideally `0.0` to `1.0`
- `suggested_cash_pct`: cash percentage to deploy before global risk caps
- `reason`: structured explanation data for admin/debug views

## Engine Candidates

### `STATS_VALUE`

Finds players whose underlying football performance looks better or worse than current Stockball pricing implies.

Primary inputs:

- recent player ratings
- minutes played and start probability
- goals, assists, xG/xA if available
- defensive contribution by position
- position-adjusted performance baselines
- market value gap
- injury/suspension risk
- current Stockball price

Formula style:

```text
alpha =
  stats_form_weight * stats_form_score
  + minutes_weight * minutes_security_score
  + valuation_weight * valuation_gap_score
  + fixture_weight * fixture_context_score
  - risk_weight * availability_risk_score
```

Example profiles:

- `STATS_VALUE_CONSERVATIVE`: high confidence threshold, low volatility tolerance, prefers regular starters.
- `STATS_VALUE_AGGRESSIVE`: accepts weaker confidence, targets larger valuation gaps, tolerates volatility.
- `BLUE_CHIP_HOLDER`: prefers expensive, liquid, high-confidence players and rarely sells.

Config schema:

```json
{
  "universe": {
    "max_candidates": 80,
    "included_positions": [
      "FWD",
      "MID",
      "DEF",
      "GK"
    ],
    "excluded_positions": [],
    "included_clubs": [],
    "excluded_clubs": [],
    "min_current_price": "0.0000",
    "max_current_price": null,
    "require_active_instrument": true
  },
  "lookbacks": {
    "form_matches": 5,
    "market_value_days": 180,
    "price_momentum_days": 7
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
    "volatility_risk": -0.1
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
    "position_baseline_enabled": true,
    "minutes_weight": 0.15,
    "form_weight": 0.1
  },
  "valuation": {
    "fair_value_blend": {
      "performance_implied_value": 0.45,
      "market_value_observation": 0.35,
      "current_stockball_price": 0.2
    },
    "min_valuation_gap_to_buy": 0.08,
    "min_overvaluation_gap_to_sell": 0.12,
    "cap_extreme_gap_at": 0.75
  },
  "decision": {
    "buy_threshold": 0.62,
    "sell_threshold": -0.45,
    "min_confidence": 0.6,
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
    "reduce_size_when_confidence_below": 0.75
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
    "enabled": false,
    "record_top_signal_count": 0,
    "include_raw_component_scores": false
  }
}
```

Config field intent:

- `universe`: limits which instruments the engine is allowed to evaluate before scoring.
- `lookbacks`: controls form confidence depth, market-value freshness, and Stockball price context. Season/prior blending and recent-form snapshots use the shared player-stat pipeline.
- `signal_weights`: combines normalized component scores into one `alpha_score`. Negative weights represent risk penalties.
- `stats_inputs`: controls the internal football-performance score before it is combined with valuation and risk signals.
- `valuation`: controls how the engine estimates fair value and how large a valuation gap must be before trading.
- `decision`: converts `alpha_score`, expected return, and confidence into buy/sell/hold intent.
- `risk`: hard portfolio and trading limits applied before submitting an order.
- `sizing`: converts conviction into a suggested order size before global caps.
- `execution`: controls cadence, randomness, cooldowns, and per-tick order count.
- `explainability`: controls whether decision detail should be persisted for admin/debug views. Keep disabled until decision logging is needed.

### `FORM_MOMENTUM`

Trades short-term football performance momentum.

Primary inputs:

- rolling ratings trend
- goals/assists trend
- recent minutes trend
- change in starting role
- upcoming fixture difficulty
- recent Stockball price movement

Formula style:

```text
alpha =
  form_trend_weight * form_momentum_score
  + role_change_weight * minutes_momentum_score
  + fixture_weight * upcoming_fixture_score
  - reversal_risk_weight * overextension_score
```

Example profiles:

- `FORM_MOMENTUM_SHORT_TERM`: reacts quickly to recent form and exits quickly.
- `ROLE_BREAKOUT_CHASER`: focuses on players gaining minutes or starting roles.

### `SOCIAL_SENTIMENT`

Trades attention, hype, news, and sentiment.

Primary inputs:

- mention volume
- mention velocity
- sentiment score
- news volume
- source credibility
- price overextension
- current holdings and liquidity

Formula style:

```text
alpha =
  mention_weight * mention_spike_score
  + sentiment_weight * sentiment_score
  + news_weight * news_velocity_score
  - overextension_weight * hype_overextension_score
```

Example profiles:

- `SOCIAL_HYPE_CHASER`: buys positive spikes quickly and accepts volatility.
- `SOCIAL_CONTRARIAN`: fades extreme hype after overextension.
- `NEWS_REACTOR`: responds only to high-confidence news events.

Config schema:

```json
{
  "universe": {
    "max_candidates": 100,
    "included_positions": [
      "FWD",
      "MID",
      "DEF",
      "GK"
    ],
    "excluded_positions": [],
    "included_clubs": [],
    "excluded_clubs": [],
    "min_current_price": "0.0000",
    "max_current_price": null,
    "require_active_instrument": true
  },
  "lookbacks": {
    "price_momentum_hours": 24
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
    "negative_news_risk": -0.35
  },
  "social_inputs": {
    "min_mentions": 10,
    "mention_spike_zscore_to_trade": 1.5,
    "positive_sentiment_threshold": 0.2,
    "negative_sentiment_threshold": -0.2,
    "trusted_source_multiplier": 1.25,
    "untrusted_source_multiplier": 0.5,
    "contrarian_mode": false
  },
  "decision": {
    "buy_threshold": 0.58,
    "sell_threshold": -0.5,
    "min_confidence": 0.55,
    "hold_band": 0.1,
    "allow_sells": true
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
    "reduce_size_when_confidence_below": 0.7
  },
  "sizing": {
    "base_cash_pct": 0.02,
    "confidence_multiplier": 1.1,
    "hype_multiplier": 1.25,
    "sentiment_multiplier": 0.8,
    "overextension_size_penalty": 0.7,
    "position_concentration_penalty": 0.8
  },
  "execution": {
    "tick_cadence_minutes": 30,
    "cooldown_minutes": 90,
    "decision_jitter_minutes": 15,
    "trade_probability": 0.45,
    "size_noise_pct": 0.25,
    "max_orders_per_tick": 1
  },
  "explainability": {
    "enabled": false,
    "record_top_signal_count": 0,
    "include_raw_component_scores": false
  }
}
```

### `BETTING_MARKET_VALUE`

Uses current player-prop odds as a compressed external estimate of player performance
probability. It does not independently interpret score, match phase, or match events.

Primary inputs:

- latest player goalscorer, assist, score-or-assist, shots, and shots-on-target probabilities
- implied-probability movement over the configured lookback
- the player's probability rank against other candidate players in the same market type
- agreement across distinct player market types
- quote recency and observation depth

Quotes must belong to an upcoming fixture with a known kickoff. Only comparable affirmative
selections (including over 0.5 lines) enter the cross-player comparison. Complementary outcomes
from the same event, market, line, and observation time are de-vigged when available.

The engine compares current Stockball price with a heuristic fair price anchored to the
instrument reference price and adjusted by probability rank and movement. Goals/assists/
score-or-assist form one confirmation family; shots/shots-on-target form another. This is a
simulation heuristic, not a calibrated prediction of investment returns.

Formula style:

```text
alpha =
  implied_probability_rank_weight * normalized_valuation_gap
  + probability_movement_weight * relative_probability_movement
  + cross_market_confirmation_weight * direction_agreement
```

Observations must be at least a minute apart. The engine holds when quotes are stale, when too few observations exist, or when too few
distinct market types confirm the signal. Negative alpha can produce a sell only when the
bot already owns the player and profile sell rules allow it.

Seeded profiles:

- `BETTING_MARKET_CONSERVATIVE`: requires three market types and two observations per selection; checks every 10 minutes and applies a 30% execution probability after a decision passes risk checks.
- `BETTING_MARKET_AGGRESSIVE`: requires two market types and at least two distinct observations per selection; checks every 3 minutes and applies a 60% execution probability after a decision passes risk checks.

Config schema:

```json
{
  "universe": {
    "max_candidates": 120,
    "included_positions": [
      "FWD",
      "MID",
      "DEF",
      "GK"
    ],
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
    "probability_movement": 0.3,
    "cross_market_confirmation": 0.15
  },
  "betting_inputs": {
    "min_distinct_market_types": 3,
    "min_observations_per_selection": 2,
    "min_implied_probability": 0.05,
    "movement_scale": 0.25,
    "market_type_weights": {
      "GOALSCORER": 0.3,
      "ASSIST": 0.2,
      "SCORE_OR_ASSIST": 0.25,
      "SHOTS": 0.1,
      "SHOTS_ON_TARGET": 0.15
    }
  },
  "decision": {
    "buy_threshold": 0.55,
    "sell_threshold": -0.55,
    "min_confidence": 0.65,
    "hold_band": 0.1,
    "allow_sells": true
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
    "reduce_size_when_confidence_below": 0.7
  },
  "sizing": {
    "base_cash_pct": 0.015,
    "confidence_multiplier": 0.8,
    "movement_multiplier": 0.5,
    "position_concentration_penalty": 0.8
  },
  "execution": {
    "tick_cadence_minutes": 10,
    "cooldown_minutes": 45,
    "decision_jitter_minutes": 5,
    "trade_probability": 0.3,
    "size_noise_pct": 0.1,
    "max_orders_per_tick": 1
  },
  "explainability": {
    "enabled": false,
    "record_top_signal_count": 0,
    "include_raw_component_scores": false
  }
}
```

### `MARKET_MOMENTUM`

Trades internal Stockball market behavior.

Primary inputs:

- Stockball price momentum
- recent buy/sell pressure
- trade volume
- number of unique buyers/sellers
- volatility
- distance from recent highs/lows

Formula style:

```text
alpha =
  price_momentum_weight * price_momentum_score
  + flow_weight * buy_sell_pressure_score
  + volume_weight * volume_confirmation_score
  - crowdedness_weight * crowded_trade_penalty
```

Example profiles:

- `MARKET_MOMENTUM_TRADER`: buys confirmed Stockball momentum.
- `BREAKOUT_TRADER`: buys new highs with volume confirmation.
- `LIQUIDITY_FOLLOWER`: trades only names with enough recent activity.

Config schema:

```json
{
  "universe": {
    "max_candidates": 120,
    "included_positions": [
      "FWD",
      "MID",
      "DEF",
      "GK"
    ],
    "excluded_positions": [],
    "included_clubs": [],
    "excluded_clubs": [],
    "min_current_price": "0.0000",
    "max_current_price": null,
    "min_recent_trades": 3,
    "min_recent_volume_cash": "250.0000",
    "require_active_instrument": true
  },
  "lookbacks": {
    "price_momentum_minutes": 240,
    "volume_window_minutes": 240,
    "buy_sell_pressure_minutes": 120,
    "volatility_window_days": 7,
    "breakout_window_days": 14
  },
  "signal_weights": {
    "price_momentum": 0.3,
    "buy_sell_pressure": 0.25,
    "volume_confirmation": 0.2,
    "breakout_strength": 0.15,
    "unique_trader_participation": 0.1,
    "stats_confirmation": 0.05,
    "crowded_trade": -0.2,
    "volatility_risk": -0.15
  },
  "market_inputs": {
    "min_price_move_pct": 0.03,
    "breakout_near_high_pct": 0.02,
    "buy_pressure_threshold": 0.6,
    "crowded_unique_buyer_threshold": 20,
    "allow_chasing_new_highs": true,
    "allow_fading_failed_breakouts": false
  },
  "decision": {
    "buy_threshold": 0.6,
    "sell_threshold": -0.5,
    "min_confidence": 0.55,
    "hold_band": 0.08,
    "allow_sells": true
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
    "reduce_size_when_confidence_below": 0.7
  },
  "sizing": {
    "base_cash_pct": 0.02,
    "confidence_multiplier": 1.1,
    "momentum_multiplier": 1.2,
    "volume_multiplier": 0.8,
    "volatility_size_penalty": 0.7,
    "position_concentration_penalty": 0.8
  },
  "execution": {
    "tick_cadence_minutes": 30,
    "cooldown_minutes": 90,
    "decision_jitter_minutes": 10,
    "trade_probability": 0.45,
    "size_noise_pct": 0.2,
    "max_orders_per_tick": 2
  },
  "explainability": {
    "enabled": false,
    "record_top_signal_count": 0,
    "include_raw_component_scores": false
  }
}
```

### `MEAN_REVERSION`

Fades sharp moves when price appears disconnected from fundamentals or external signals.

Primary inputs:

- short-term price move
- volatility
- deviation from rolling average
- signal confirmation or lack of confirmation
- recent trade imbalance
- social hype overextension

Formula style:

```text
alpha =
  reversion_weight * price_deviation_score
  - confirmation_weight * confirming_signal_score
  - trend_strength_weight * trend_strength_score
```

Example profiles:

- `MEAN_REVERSION_TRADER`: fades large unsupported moves.
- `HYPE_FADE_TRADER`: fades social spikes when price moved too far.

### `UPSIDE_HUNTER`

Targets players with asymmetric upside even if median confidence is lower.

Primary inputs:

- low current Stockball price
- age or prospect metadata if available
- minutes growth
- bench-to-starter probability
- recent role changes
- positive tails in stats/social/betting signals
- volatility

Formula style:

```text
alpha =
  upside_weight * breakout_upside_score
  + cheapness_weight * low_price_optional_value_score
  + role_weight * role_growth_score
  - downside_weight * availability_or_minutes_risk_score
```

Example profiles:

- `HIGH_UPSIDE_PROSPECT_HUNTER`: accepts high volatility for breakout potential.
- `CHEAP_OPTIONALITY_TRADER`: buys small positions in many low-priced players.

### `EVENT_REACTION`

Implemented. Trades the surprise in a player's latest FotMob-rated match, confirmed by betting
markets. Profiles: `EVENT_REACTION_MEASURED` (default) and `EVENT_REACTION_FAST`.

Inputs per candidate (`MatchEventContext`, loaded over the last 72 hours):

- the match rating and minutes, and the player's steadied rating before that match
- `known_at`: when the ratings were first observed. Replays never react before then, and a
  match must also have kicked off within the window, so backfills never read as fresh events.
- closing quotes: the player's last pre-kickoff quote per selection for a bookmaker event
  kicking off within three hours of the match. Providers are matched by linked player and
  kickoff time, never by a guessed fixture id.
- next-fixture quotes over `lookbacks.betting_movement_minutes`
- Stockball prices since `known_at`

Formula:

```text
surprise       = clamp((rating - baseline) / 0.77 / surprise_scale) * minutes_share
                 (0 below min_minutes)
match_surprise = surprise - expectation_weight * expectation * |surprise|
                 (expectation: -1..1 rank of closing involvement probabilities)
alpha = 0.5^(age / half_life) * (w_surprise * match_surprise + w_odds * next_match_movement)
      + direction * w_price_already_moved * max(price move with the surprise / priced_in_move_pct, 0)
      + w_season_quality * stats_confirmation
```

A big game from an outsider is a bigger surprise than one from the favourite, and a
favourite's flop is a deeper disappointment. Confidence rises with minutes, the depth of the
baseline, and each betting signal present. The measured profile's 0.6 floor effectively
requires betting confirmation.

Herding controls: each bot waits `reaction_delay_minutes`, jittered from 0.5x to 1.5x per
bot and match. Delays, half-lives, surprise scales and holding periods are randomized per
bot at spawn.

Exits: a position the bot itself traded is sold (`unwind_fraction`) once
`holding_period_hours` have passed since its last trade, unless a fresh match is still
within its reaction delay. Positions the bot was only allocated at bootstrap are never
unwound, because they were never a reaction. Ordinary sells follow poor matches.

Still proposals for this family: lineup confirmations, injury and suspension news, and
return-to-play signals.

### `PORTFOLIO_REBALANCER`

Trades to maintain a target portfolio shape rather than pure alpha.

Primary inputs:

- current positions
- cash balance
- target exposure by player/team/position
- realized and unrealized gains
- concentration limits
- recent volatility

Formula style:

```text
rebalance_need =
  target_exposure
  - current_exposure
```

Example profiles:

- `PORTFOLIO_REBALANCER`: trims concentration and deploys idle cash.
- `RISK_PARITY_ALLOCATOR`: sizes positions inversely to volatility.
- `PROFIT_TAKER`: sells partial positions after strong gains.

Config schema:

```json
{
  "portfolio_targets": {
    "target_cash_pct": 0.15,
    "min_cash_pct": 0.08,
    "max_cash_pct": 0.35,
    "max_player_position_pct": 0.12,
    "max_team_exposure_pct": 0.25,
    "max_position_count": 30,
    "min_position_cash_value": "25.0000"
  },
  "rebalance_rules": {
    "cash_deploy_threshold_pct": 0.08,
    "cash_raise_threshold_pct": 0.08,
    "player_overweight_threshold_pct": 0.03,
    "team_overweight_threshold_pct": 0.05,
    "trim_to_target_pct": 0.5,
    "profit_take_return_pct": 0.25,
    "loss_reduce_return_pct": -0.2,
    "allow_new_positions": true,
    "allow_full_exit": false
  },
  "candidate_selection": {
    "max_buy_candidates": 50,
    "max_sell_candidates": 50,
    "prefer_existing_watchlist": true,
    "prefer_positive_alpha_when_deploying_cash": true,
    "avoid_frozen_or_inactive_instruments": true
  },
  "signal_weights": {
    "portfolio_drift": 0.45,
    "cash_drift": 0.25,
    "concentration_risk": 0.2,
    "profit_taking": 0.15,
    "positive_alpha_tiebreaker": 0.1,
    "volatility_risk": -0.15
  },
  "decision": {
    "allow_buys": true,
    "allow_sells": true
  },
  "risk": {
    "max_trade_cash_pct": 0.035,
    "min_trade_cash_amount": "25.0000",
    "max_trade_cash_amount": "1500.0000",
    "max_daily_trades": 12,
    "max_daily_turnover_pct": 0.25,
    "volatility_tolerance": 0.5
  },
  "sizing": {
    "base_rebalance_pct": 0.4,
    "cash_drift_multiplier": 0.8,
    "concentration_multiplier": 1.0,
    "profit_take_multiplier": 0.5,
    "volatility_size_penalty": 0.5
  },
  "execution": {
    "tick_cadence_minutes": 180,
    "cooldown_minutes": 360,
    "decision_jitter_minutes": 30,
    "trade_probability": 0.4,
    "size_noise_pct": 0.1,
    "max_orders_per_tick": 3
  },
  "explainability": {
    "enabled": false,
    "record_top_signal_count": 0,
    "include_raw_component_scores": false
  }
}
```

### `NOISE`

Creates realistic low-conviction retail behavior.

Primary inputs:

- weak random preference
- small bias toward popular players
- small bias toward recent movers
- cash balance
- current holdings
- configurable buy/sell tendency

Formula style:

```text
alpha =
  random_component
  + popularity_bias
  + recent_mover_bias
  + holding_bias
```

Example profiles:

- `NOISE_RETAIL_BUYER`: mostly buys small amounts with weak positive bias.
- `NOISE_RETAIL_SELLER`: occasionally sells holdings for liquidity or profit-taking.
- `CASUAL_FAN_TRADER`: overweights recognizable names and club preferences.

Config schema:

```json
{
  "universe": {
    "max_candidates": 150,
    "included_positions": [
      "FWD",
      "MID",
      "DEF",
      "GK"
    ],
    "excluded_positions": [],
    "included_clubs": [],
    "excluded_clubs": [],
    "favorite_clubs": [],
    "favorite_player_ids": [],
    "min_current_price": "0.0000",
    "max_current_price": null,
    "require_active_instrument": true
  },
  "randomness": {
    "random_alpha_min": -0.4,
    "random_alpha_max": 0.4,
    "buy_bias": 0.08,
    "sell_bias": 0.0,
    "favorite_club_bias": 0.12,
    "recognizable_player_bias": 0.1,
    "recent_mover_bias": 0.08,
    "holding_bias": 0.05
  },
  "signal_weights": {
    "random_component": 0.55,
    "popularity_bias": 0.15,
    "recent_mover_bias": 0.1,
    "favorite_bias": 0.1,
    "holding_bias": 0.05,
    "cash_pressure": 0.05,
    "volatility_risk": -0.05
  },
  "decision": {
    "buy_threshold": 0.25,
    "sell_threshold": -0.3,
    "min_confidence": 0.2,
    "hold_band": 0.15,
    "allow_sells": true
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
    "volatility_tolerance": 0.8
  },
  "sizing": {
    "base_cash_pct": 0.008,
    "confidence_multiplier": 0.5,
    "random_size_multiplier_min": 0.5,
    "random_size_multiplier_max": 1.5,
    "position_concentration_penalty": 0.7
  },
  "execution": {
    "tick_cadence_minutes": 60,
    "cooldown_minutes": 120,
    "decision_jitter_minutes": 30,
    "trade_probability": 0.25,
    "size_noise_pct": 0.35,
    "max_orders_per_tick": 1
  },
  "explainability": {
    "enabled": false,
    "record_top_signal_count": 0,
    "include_raw_component_scores": false
  }
}
```

## Implemented Engine Set

1. `NOISE`
2. `MARKET_MOMENTUM`
3. `STATS_VALUE`
4. `SOCIAL_SENTIMENT`
5. `PORTFOLIO_REBALANCER`
6. `BETTING_MARKET_VALUE`
7. `EVENT_REACTION`

These engines provide baseline market activity, price-following behavior, fundamental
behavior, hype behavior, betting-probability behavior, post-match reaction, and portfolio
maintenance. Add `MEAN_REVERSION` and `UPSIDE_HUNTER` after the relevant signal feeds and
decision traces are in place. Promote `FORM_MOMENTUM` from a profile to an engine only if it
needs mechanics `STATS_VALUE` lacks.

## Diversity Rules

Bots should vary across more than signal weights. Profiles should differ in:

- candidate universe
- preferred positions
- preferred clubs or popularity bands
- time horizon
- confidence threshold
- volatility tolerance
- max trade size
- max position concentration
- buy/sell threshold
- cooldown period
- tick cadence
- reaction delay
- willingness to sell
- cash deployment target
- number of candidates evaluated per tick

The same signal snapshot should not cause every bot to place the same order. Diversity is working when different profiles can reasonably buy, sell, or hold the same player based on their engine and config.
