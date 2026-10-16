# Trading Engine Index Funds Module

## Purpose

Owns index funds: instruments whose unit is a fixed basket of player shares.

## How a Fund Works

- A fund is an `INDEX_FUND` instrument with no player, supply, or price curve. One unit holds
  `shares_per_unit` of each constituent, stored in `index_constituents`. Team funds hold one
  share of every league player at a club.
- A fund's price is the value of its basket at its constituents' current prices. It never moves
  on its own: buying units buys each constituent on that player's curve, so the fund only moves
  because its players do.
- Buying `n` units records the trader's fund trade, debits its full cost, and has the custody
  account (`system-index-fund-custody`) buy `n × shares_per_unit` of every constituent. Selling
  sells them back and credits the trader. Custody legs are ordinary orders and trades, linked to
  the fund trade by `trades.index_trade_id`, with no ledger entry of their own: the cash moves
  between the trader and the market.
- Every trade in a constituent, directly or through a fund, reprices every fund holding it and
  records an `INDEX_REVALUATION` snapshot linked to that trade. The fund's own trade records
  `TRADE_BUY` or `TRADE_SELL`.
- A unit trades as a whole, so a fund trades only while it and every constituent are `ACTIVE`.
  A match-day freeze on a club's players pauses that club's fund.

## Lock Order

Flows that touch funds and players lock every affected fund row first, then the player rows,
each group in id order, then portfolios. Player-share orders follow the same order, locking the
funds that hold the traded player before the player, so fund and player orders cannot deadlock.

## Creating Funds

`POST /internal/v1/instruments/index-funds/create` lists a fund over a basket, priced at the
basket's value, with a `SEED` snapshot. It is idempotent by symbol: the same symbol and basket
return the existing fund; a different basket under a taken symbol is refused. The worker's
`create-team-index-funds` command and `CREATE_TEAM_INDEX_FUNDS` admin job list one fund per
league club from the current roster.

A basket is fixed once listed, because the custody account's holdings must match the units in
issue. Changing a basket (a transfer, a rebalance) needs custody trades and is not built yet.

## Boundaries

- Owns `index_funds` and `index_constituents`.
- Fund prices are written through `instruments`, trades through `execution`, positions through
  `positions`, and price history through `snapshots`.
