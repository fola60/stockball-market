# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Stockball is primarily for casual Premier League football fans who are also comfortable with trading concepts. They use it to discover which players are moving in the market, evaluate an individual player, buy or sell player shares, and understand how those positions are performing without needing professional-market expertise.

## Product Purpose

Stockball turns Premier League player interest into a virtual-cash market. Users can buy and sell long-only player-share instruments, follow trading-driven price movements, and manage a portfolio. Success means a football fan can understand the market quickly, find an interesting player, make a trade confidently, and see the result reflected clearly in their holdings.

## Positioning

Stockball combines the familiarity of Premier League players with a simulated stock-market mechanism: player prices move only because shares are bought or sold. Football performance, social attention, and other external signals may influence participant behavior, but they do not directly reprice a player in V1.

## Operating Context

- The market homepage is the primary discovery surface and emphasizes the best- and worst-performing players.
- Each player stock page contains the information needed to evaluate that player; a separate transfer-window surface is not required.
- The portfolio is a separate destination for cash, holdings, allocation, and performance.
- Trading freezes at lineup lock for players involved in live matches and resumes after post-match settlement.
- Real users and tagged synthetic traders participate through the same trading path. Synthetic traders provide believable activity and liquidity before organic demand is sufficient.

## Capabilities and Constraints

- V1 supports Premier League `PLAYER_SHARE` instruments only.
- Trading uses virtual cash; no real-money trading is offered.
- Positions are long-only. Shorting, margin, derivatives, expiry, exercise, and settlement contracts are out of scope.
- Users trade against a platform quote rather than a user-to-user order book.
- Every executed buy raises the quoted price and every executed sell lowers it using the configured net-demand price curve.
- External football statistics, sentiment, and betting-market observations can inform synthetic trader decisions but cannot mutate prices directly.
- Team funds, national-team funds, and a transfer-window page are outside V1 scope.
- The existing web implementation uses Next.js-compatible React, TypeScript, and Tailwind CSS.
- The cadence for synthetic-trader credit top-ups remains undecided between weekly and monthly.

## Brand Commitments

- The product name is **Stockball**.
- Product language should combine recognizable football terms with understandable market terms, explaining specialist concepts when needed for casual fans.
- Currency is explicitly virtual and must not be presented in a way that implies real-money investing.

## Evidence on Hand

- The durable V1 rules and build order are documented in `../../PROJECT_PLAN.md`.
- The market homepage and portfolio implementation live in `app/page.tsx`, `app/components/market-shell.tsx`, and `app/portfolio/page.tsx`.
- Trading contracts and service behavior exist elsewhere in the repository, including `../../packages/contracts/` and `../../services/trading-engine/`.
- No verified testimonials, customer counts, investment returns, licenses, or performance claims are currently available; future surfaces must not fabricate them.

## Product Principles

1. Lead with the player market, not the account balance.
2. Make trading concepts legible to football fans without stripping away useful market information.
3. Keep price formation transparent: trading activity moves prices; football signals influence traders.
4. Keep player evaluation and trading context together on the player stock page.
5. Present virtual trading clearly and never imply real-money investment outcomes.
