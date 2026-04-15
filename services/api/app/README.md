# API Application Modules

## Purpose

Contains the API service application modules.

## Modules

- `accounts`: users, admins, sessions, roles, and synthetic bot account provisioning.
- `instruments`: read APIs for instruments and market data.
- `portfolios`: read APIs for cash, positions, and PnL.
- `orders`: public order requests and trading-engine forwarding.
- `admin`: internal admin endpoints.
- `clients`: clients for internal service calls.

## Boundary Rule

The API application can accept requests and return views, but it must not execute trades or mutate market-critical state directly.
