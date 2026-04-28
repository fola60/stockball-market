# Worker Signals Module

## Purpose

Turns ingested facts into interpreted observations for synthetic trader strategies.

Signals answer: "What does the external data mean for bot behavior?"

## Responsibilities

- Read raw or normalized ingestion records.
- Calculate signal values such as hype, sentiment, form, or momentum.
- Store signal observations.
- Provide inputs to synthetic trader strategies.

## Submodules

- `social`: mention volume, sentiment, and hype-spike signals.
- `stats`: football performance and availability signals.
- Future `market`: Stockball price momentum, volatility, order-flow signals, and external pre-match betting market context.

## Boundaries

- Signals do not directly mutate prices in V1.
- Signals do not execute trades.
- Synthetic traders consume signals and decide whether to trade.
- Trades through the trading engine are the only way signals can indirectly affect price.
