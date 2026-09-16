# Trading Engine

## Purpose

The trading engine is the consistency-critical market service.

It is the only service allowed to execute trades or mutate prices, balances, positions, trade records, and price snapshots.

## Responsibilities

- Execute buy and sell orders.
- Enforce market freezes.
- Check cash and share availability.
- Mutate portfolio cash and positions.
- Record orders and trades.
- Quote and apply the net-demand price curve.
- Record price snapshots.
- Apply ledger credits for scheduled top-ups.
- Protect retry-sensitive commands with idempotency.

## Must Not Own

- User authentication.
- Public API routing.
- External data ingestion.
- Social/stat signal interpretation.
- Synthetic trader strategy decisions.

## Internal Modules

- `orders`: order commands and order records.
- `execution`: trade execution orchestration.
- `price_impact`: price movement calculation.
- `ledger`: cash movement records and balance changes.
- `topups`: idempotent scheduled cash-credit commands.
- `portfolios`: portfolio summary and cash balance coordination.
- `positions`: account exposure to tradable instruments.
- `instruments`: tradable instrument price/status state.
- `freezes`: market halt enforcement.
- `snapshots`: price history.
- `idempotency`: safe retries.
