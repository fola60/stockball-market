# Worker Signals Market Module

## Purpose

Future module for interpreting internal market behavior for synthetic trader strategies.

## Responsibilities

- Calculate price momentum.
- Calculate recent volume and buy/sell pressure.
- Detect unusual trading activity.
- Produce market-watching signals for bots.

## Boundaries

- Reads market data produced by the trading engine.
- Does not execute trades.
- Does not directly mutate prices.
- Synthetic traders consume these signals and send trade commands to the trading engine.
