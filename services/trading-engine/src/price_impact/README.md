# Trading Engine Price Impact Module

## Purpose

Owns the player-share price curve and trade quoting calculation.

## Curve Rule

- Each instrument stores its reference price, net shares purchased, curve depth, and a
  full-supply price multiplier.
- Net shares purchased means shares bought through the trading engine minus shares sold through
  it since the curve was last anchored. It is independent of the initial allocation of shares
  to portfolios.
- The quoted price is `reference_price × multiplier ^ (net_shares_purchased ÷ curve_depth_shares)`.
  Net buying of `curve_depth_shares` reaches `multiplier` times the reference price; the same
  net selling reaches its reciprocal. Trades beyond either end are refused.
- Curve depth sets volatility. It is a fraction of `shares_outstanding`, because almost all of a
  player's supply sits in reserve and never trades: a curve spanning the full supply barely
  moved under real trading (a median 0.03% a day in October 2026). Since October 2026 the
  intended calibration is a multiplier of 20 over 1/15 of the supply.
- The multiplier only acts through its logarithm, so raising it changes volatility far less than
  changing the depth: 2.5 to 4 made prices 1.5 times as responsive; a 15 times shallower curve
  makes them 15 times as responsive.
- Trade cost comes from one cumulative cost function for the curve. Each order subtracts its
  starting cumulative cost from its ending cumulative cost. This makes a combined order and
  equivalent consecutive orders produce the same price and stored cost.

## Recalibration

Changing a curve's reference, multiplier, or depth is a rebase. The database requires a rebase
to reset net shares purchased and set the reference to the current price, so no price moves
without a trade, and records every rebase in `instrument_price_curve_rebases`.

`POST /internal/v1/instruments/price-curves/recalibrate` rebases every player-share curve to a
new multiplier and depth divisor in one transaction. Operators run it through the worker:

```sh
stockball-worker recalibrate-price-curves --multiplier 20 --depth-divisor 15 --reason "..."
stockball-worker recalibrate-price-curves --multiplier 20 --depth-divisor 15 --reason "..." --apply
```

Without `--apply` the engine performs the recalibration, reports it, and rolls back. Newly seeded
players start on `STOCKBALL_DEFAULT_FULL_SUPPLY_PRICE_MULTIPLIER` and
`STOCKBALL_DEFAULT_CURVE_DEPTH_DIVISOR` (default 20 and 15). These settings never change
existing curves, because changing a curve outside a rebase would reprice every player that has
net demand.

## Responsibilities

- Calculate the old price, new price, average execution price, trade cost, and next curve state.
- Keep price math isolated and testable.
- Enforce the positive and negative curve limits.
- Preserve twelve decimal places at storage boundaries. Cumulative cost is rounded before taking
  the difference so consecutive trades telescope without accumulating per-order rounding drift.
  Four-decimal formatting belongs to the presentation layer.

## Boundaries

- Stats and sentiment must not call this module directly in V1.
- Signals influence synthetic traders.
- Synthetic traders place trades.
- Trades cause price impact.

Prices move only through executed buy and sell activity.
