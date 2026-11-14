# Worker Forecasting Module

## Purpose

Predicts where a player's FotMob match rating is heading, so synthetic traders can bet on
improvement or decline before it shows up in the season rating the stats engines price.

This is a forecast of future *performance*. It is not a sentiment model: there is no sentiment
history to train one on yet.

## What is predicted

For each player and each horizon (his next 1, 5 and 10 rated appearances), the model predicts
how far the minutes-weighted rating over those appearances will land from his steadied season
rating (`app.player_stats.ratings`, the `average_rating` the stats bots already see). A
prediction of zero means "no change from what is already priced".

A forecast is conditional on the player playing enough to be rated, and players who keep
their place tend to rate slightly above their season figure, so the typical forecast is a
little above zero. `FORECAST_VALUE` bots trade each forecast relative to the median of their
candidates for that reason.

## Layout

- `features.py`: turns match history into rows of what was knowable at one moment. Every
  feature uses only matches that kicked off before the row's as-of time, and reference levels
  (the league's typical rating) come from the season before. `tests/test_forecasting.py`
  rewrites the future and checks that no earlier row changes.
- `dataset.py`: read-only SQL for appearances, fixtures, birth dates and dated market values.
- `ridge.py`: weighted ridge regression in the standard library. The worker image has no
  numerical packages, the data is small, and a model stored as JSON coefficients needs no
  pickles and explains each forecast as named contributions.
- `training.py`: walk-forward evaluation and the promotion rule.
- `service.py`: `train()` and `refresh()`.
- `repository.py`: `forecast_models` and `player_forecasts` (migration 0042).
- `backfill.py`: dated Transfermarkt value history.
- `odds.py`: football-data.co.uk match result odds, linked to FotMob fixtures
  (`match_result_odds`). A team's recent odds are the model's measure of team strength; in
  testing they roughly doubled its skill over using the team's own recent ratings.

## Evaluation and promotion

The newest season with at least 300 matured rows is held out. The model is fitted only on
outcomes known before that season began; the ridge penalty is tuned on the newest quarter of
that training window, never on the holdout. `skill` is `1 - model MSE / baseline MSE`, where
the baseline predicts no change. A horizon is `usable` only when its skill is above zero.

A trained model becomes `ACTIVE` when at least one horizon is usable and its total skill is
not more than 0.01 below the active model's. Otherwise it is stored as `REJECTED` with the
reason, and the previous model stays active. Forecasts are written only for usable horizons,
so a horizon the model cannot beat the baseline on is simply absent and its bots hold.

## Running

```sh
stockball-worker train-forecast-model --dry-run   # evaluate, store nothing
stockball-worker train-forecast-model             # store, promote if it earns it
stockball-worker refresh-forecasts                # today's forecasts; retrains when due
stockball-worker refresh-forecasts --no-retrain
```

With `STOCKBALL_FORECAST_SIGNALS_ENABLED=true`:

- the scheduled FotMob ratings job calls `refresh()` whenever it stores new ratings. A refresh
  first downloads the current season's odds file (a failure is logged and skipped), then
  retrains first when there is no active model or the active one is older than seven days.
  A forecasting failure is recorded in the job's metrics and never fails the ingestion;
- synthetic traders load each player's latest forecast, which only `FORECAST_VALUE` bots read.

The flag is off by default. With it off nothing in this module runs and no existing engine or
bot behaves differently.

## Backfilling history

```sh
# Match ratings: every finished match of earlier seasons (resumable).
stockball-worker ingest-fotmob-ratings --season 2024 --backfill --archive-dir /path/to/archive

# Match odds: download whole seasons, or pass files with --csv.
stockball-worker import-match-odds --season 2022 --season 2023 --season 2024 --season 2025

# Transfermarkt: every dated value for players the regular import already matched.
stockball-worker backfill-market-value-history --valuations-csv /path/to/player_valuations.csv
```

Earlier seasons' players who are not on the current roster stay keyed by FotMob id and still
train the model; forecasts are only written for players with a canonical id. Every other
reader of `player_market_value_observations` takes the latest value, which the value-history
backfill never changes.

## Rollout

Nothing here is live until these steps are taken, in this order:

1. Deploy the code. Migration 0042 must not be applied before it: the migration seeds
   `FORECAST_VALUE` profiles, and an older worker cannot parse that engine name.
2. Import match odds for every season with ratings (`import-match-odds --season ...`).
3. `train-forecast-model`, and read the evaluation it prints.
4. Set `STOCKBALL_FORECAST_SIGNALS_ENABLED=true` for the trading worker and the ingestion
   worker. Forecasts are then refreshed after each FotMob ingestion.
5. Spawn forecast bots when wanted, for example
   `spawn-synthetic-traders --config-key FORECAST_FORM_RUN --count 25`. They need funding
   like any other bot.

To back out, unset the flag: forecasts stop being written and read, and forecast bots hold.

## Boundaries

- Writes only `forecast_models`, `player_forecasts`, `match_result_odds` and, for the
  backfill, dated rows in `player_market_value_observations`.
- Does not place trades or touch prices. Forecasts reach the market only through
  `FORECAST_VALUE` bots' orders.
