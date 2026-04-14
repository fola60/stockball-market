# API Service

## Purpose

The API service exposes Stockball's public and admin HTTP API.

It is the entry point for clients and the admin UI, but it does not execute trades. Trade execution, price changes, holdings mutations, and trade-related cash mutations must go through the trading engine.

## Responsibilities

- Authenticate users and admins.
- Expose read APIs for assets, portfolios, price history, and market status.
- Accept user order requests.
- Validate request shape and user identity.
- Forward trade commands to the trading engine.
- Expose admin APIs for inspecting market, bot, freeze, and ingestion state.

## Must Not Own

- Trade execution.
- Price mutation.
- Holding mutation.
- Trade-related cash mutation.
- Synthetic trader decisions.
- External data ingestion.

## Internal Modules

- `accounts`: user identity, sessions, auth, and roles.
- `assets`: read APIs for player assets and market data.
- `portfolios`: read APIs for cash, holdings, and PnL.
- `orders`: public order endpoint and request validation.
- `admin`: admin-only read and control endpoints.
- `clients`: service clients, especially the trading-engine client.
