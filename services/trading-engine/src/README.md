# Trading Engine Source Modules

## Purpose

Contains the Rust modules that implement market execution and state mutation.

## Modules

- `orders`: order commands and records.
- `execution`: buy/sell execution orchestration.
- `price_impact`: V1 price movement formula.
- `ledger`: cash movements and audit entries.
- `portfolios`: holdings and portfolio mutations.
- `assets`: tradable player asset state.
- `freezes`: market freeze enforcement.
- `snapshots`: historical price records.
- `idempotency`: retry safety.

## Boundary Rule

Market-critical mutations should be handled here and exposed through internal APIs, not duplicated in the API or worker services.
