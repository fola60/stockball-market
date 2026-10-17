# Trading Engine Index Funds Module

## Purpose

Owns index funds: instruments whose unit is a fixed basket of player shares.

## How a Fund Works

- A fund is an `INDEX_FUND` instrument with no player, supply, or price curve. One unit holds
  `shares_per_unit` of each constituent, stored in `index_constituents`, plus `cash_per_unit`
  held by the custody account (`system-index-fund-custody`).
- A fund's price is its basket at current prices plus its cash. It never moves on its own:
  buying units buys each constituent on that player's curve, so the fund only moves because its
  players do.
- Buying `n` units records the trader's fund trade, debits its full cost, has custody buy
  `n × shares_per_unit` of every constituent, and moves `n × cash_per_unit` into custody
  (`INDEX_FUND_CASH_IN`). Selling reverses it (`INDEX_FUND_CASH_OUT`). Buy legs round up and
  sale legs round down, so custody always holds at least what every unit in issue needs.
  Custody legs link to the fund trade through `trades.index_trade_id`.
- Every trade in a constituent reprices every fund holding it and records an
  `INDEX_REVALUATION` snapshot. The fund's own trade records `TRADE_BUY` or `TRADE_SELL`.
- A unit trades as a whole, so a fund trades only while it and every constituent are `ACTIVE`.
  A match-day freeze on a club's players pauses that club's fund.

## Following a Rule

The worker re-evaluates each fund's rule daily (`REVIEW_INDEX_FUNDS`) and asks the engine to
rebalance when the result changes or the fund holds cash from a buyout.

`POST /internal/v1/instruments/index-funds/rebalance` moves a fund to a new membership in which
every member holds the same shares per unit, without changing what a unit is worth apart from
price impact:

1. The target is the unit's current value spread evenly over the new members' prices. A member
   that cannot trade (a player halted until their buyout) keeps its shares and is left out of
   the spread.
2. With units in issue, custody sells what leaves or shrinks, then spends the proceeds and the
   fund's cash on what joins or grows. Purchases are scaled down to the cash available, since
   price impact makes them dearer than planned, and the remainder stays as cash per unit. Each
   member's new shares per unit is what custody now holds for the fund, rounded down.
3. With no units in issue nothing trades; the basket is rewritten at current prices.

Custody's trades are ordinary orders and trades linked by `trades.index_rebalance_id`, with
ledger entries on custody's own portfolio. Every basket change is recorded in
`index_fund_rebalances`; the request id makes a retried rebalance replay its record.

## Delisting

A player who leaves the league is halted by the roster sync and, after a grace period, delisted
through the `delistings` module: every holder, custody included, is paid the last price
(`DELISTING_BUYOUT`) and the share is marked `DELISTED`. Each fund that held it swaps those shares
for the same value in cash per unit, recorded as a `DELISTING` basket change. The next review
reinvests the cash.

## Lock Order

Flows that touch funds and players lock every affected fund row first, then the player rows,
each group in id order, then portfolios, with the custody portfolio always last. Player-share
orders follow the same order, locking the funds that hold the traded player before the player,
so fund, player, rebalance, and delisting flows cannot deadlock.

## Creating Funds

`POST /internal/v1/instruments/index-funds/create` lists a fund over a basket, priced at the
basket's value, with a `SEED` snapshot. It is idempotent by symbol: the same symbol and basket
return the existing fund; a different basket under a taken symbol is refused.

## Boundaries

- Owns `index_funds`, `index_constituents`, and `index_fund_rebalances`.
- Fund prices are written through `instruments`, trades through `execution`, cash through
  `ledger`, positions through `positions`, and price history through `snapshots`.
