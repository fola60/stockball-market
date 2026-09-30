# Trading Engine Source Modules

## Purpose

Contains the Rust modules that implement market execution and state mutation.

## Modules

- `orders`: order commands and records.
- `execution`: buy/sell execution orchestration.
- `price_impact`: curved price movement and exact trade quoting.
- `ledger`: cash movements and audit entries.
- `topups`: validated, idempotent weekly and monthly ledger credits.
- `provisioning`: idempotent one-off setup writes: a new portfolio's opening balance, the initial share supply of pre-market instruments, and pre-market price anchoring.
- `portfolios`: portfolio summary and cash balance coordination.
- `positions`: account exposure to tradable instruments.
- `instruments`: tradable instrument state.
- `freezes`: market freeze enforcement.
- `snapshots`: historical price records.
- `idempotency`: retry safety.

## Boundary Rule

Market-critical mutations should be handled here and exposed through internal APIs, not duplicated in the API or worker services.

Detailed module ownership rules are defined in `MODULE_RULES.md`.
