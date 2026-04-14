# Trading Engine Ledger Module

## Purpose

Owns cash movements and cash balance auditability.

Every virtual-cash credit or debit should create a ledger entry.

## Responsibilities

- Debit cash for buy trades.
- Credit cash for sell trades.
- Credit scheduled weekly/monthly top-ups.
- Support future admin adjustments or reversals.
- Store reason, amount, account, source command, and timestamp for each cash movement.
- Update portfolio cash balances safely.

## Ledger Reasons

- `TRADE_BUY_DEBIT`
- `TRADE_SELL_CREDIT`
- `WEEKLY_TOPUP`
- `MONTHLY_TOPUP`
- `ADMIN_ADJUSTMENT`
- `REVERSAL`

## Boundaries

- The worker service decides when a top-up is due.
- This module applies the top-up credit.
- The API service may read ledger history but must not write ledger entries.
- Holdings are owned by `portfolios`; cash audit is owned by `ledger`.
