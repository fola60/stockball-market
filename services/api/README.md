# API Service

## Purpose

The API service exposes Stockball's public and admin HTTP API.

It is the entry point for clients and the admin UI, but it does not execute trades. Trade execution, price changes, position mutations, and trade-related cash mutations must go through the trading engine.

## Responsibilities

- Authenticate users and admins.
- Provision tagged synthetic trader accounts when requested by internal tooling.
- Expose read APIs for instruments, portfolios, price history, and market status.
- Accept user order requests.
- Validate request shape and user identity.
- Forward trade commands to the trading engine.
- Expose admin APIs for inspecting market, bot, freeze, and ingestion state.

## Must Not Own

- Trade execution.
- Price mutation.
- Position mutation.
- Trade-related cash mutation.
- Synthetic trader decisions.
- External data ingestion.

## Internal Modules

- `accounts`: user identity, sessions, auth, roles, and synthetic bot account provisioning.
- `instruments`: read APIs for tradable instruments and market data.
- `portfolios`: read APIs for cash, positions, and PnL.
- `orders`: public order endpoint and request validation.
- `admin`: admin-only read and control endpoints.
- `clients`: service clients, especially the trading-engine client.
