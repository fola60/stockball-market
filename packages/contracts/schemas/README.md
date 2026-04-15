# Shared Schemas

## Purpose

Stores shared JSON schemas or schema fragments used across service contracts.

## Responsibilities

- Define common payload shapes.
- Define shared enums such as order side, instrument status, trade reason, instrument type, and ledger reason.
- Reduce drift between API, worker, and trading-engine contracts.
- Represent shared trading models such as instruments, positions, portfolios, orders, trades, ledger entries, price snapshots, and execution payloads.

## Schemas

- `common.schema.json`: shared primitives, enums, and error responses.
- `trading.schema.json`: first-slice trading models and execute-order payloads.

## Boundaries

- Schemas do not contain service behavior.
- Services still own validation and business rules.
- Decimal money and quantity values are strings in JSON contracts to avoid float precision bugs.
- V1 schemas include `PLAYER_SHARE` instruments only and do not model derivatives.
