# API Admin Module

## Purpose

Provides admin-only API endpoints for operating and inspecting the market.

## Responsibilities

- Show market state, price history, and asset status.
- Show synthetic trader accounts and activity.
- Show order and trade history.
- Show frozen assets and freeze reasons.
- Show ingestion, job, and signal health.
- Expose safe admin controls that call the correct owning service.

## Boundaries

- Reads across market and operational data for visibility.
- Must not execute trades directly.
- Must not write prices, holdings, or balances directly.
- Any admin action that changes market state must call the trading engine or worker service through an explicit service client.
