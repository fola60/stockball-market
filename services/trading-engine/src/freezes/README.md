# Trading Engine Freezes Module

## Purpose

Owns market-freeze enforcement.

## Responsibilities

- Apply freezes to player assets.
- Remove freezes from player assets.
- Store freeze reason, start time, optional end time, and status.
- Check whether an asset is currently frozen during order execution.
- Reject orders for frozen assets.

## Freeze Reasons

- `LINEUP_LOCK`
- `LIVE_MATCH`
- `POST_MATCH_SETTLEMENT`
- `ADMIN_HALT`
- `DATA_ISSUE`

## Boundaries

- The worker service may detect fixture events.
- This module decides whether trading is allowed for a given asset.
- The API service and worker service must not bypass freeze checks.
