# Worker Signals Market Module

## Purpose

Future module for interpreting internal market behavior for synthetic trader strategies.

## Responsibilities

- Calculate price momentum.
- Calculate recent volume and buy/sell pressure.
- Detect unusual trading activity.
- Interpret future pre-match betting market observations as context signals.
- Produce market-watching signals for bots.

## Boundaries

- Reads market data produced by the trading engine.
- May read external betting market observations produced by ingestion.
- Does not execute trades.
- Does not directly mutate prices.
- Synthetic traders consume these signals and send trade commands to the trading engine.
- External betting odds must not directly set Stockball prices.
