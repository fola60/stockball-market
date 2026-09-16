# Trading Engine Price Impact Module

## Purpose

Owns the player-share price curve and trade quoting calculation.

## Curve Rule

- Each instrument stores its reference price, net shares purchased, shares outstanding, and a
  configurable full-supply price multiplier.
- Net shares purchased means shares bought through the trading engine minus shares sold through
  it. It starts at zero and is independent of the initial allocation of shares to portfolios.
- The default full-supply multiplier is `2.5`. At net purchases equal to shares outstanding, the
  quote is 2.5 times the reference price. At the equivalent net-selling limit, it is 0.4 times the
  reference price.
- The quoted-price multiplier is the full-supply multiplier raised to the demand ratio. For
  example, the default curve uses `2.5 ^ demand_ratio`.
- Trade cost comes from one cumulative cost function for the curve. Each order subtracts its
  starting cumulative cost from its ending cumulative cost. This makes a combined order and
  equivalent consecutive orders produce the same price and stored cost.

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
