# Trading Engine Freezes Module

## Purpose

Owns market-freeze enforcement.

## Responsibilities

- Apply freezes to instruments.
- Remove freezes from instruments.
- Store freeze reason, start time, optional end time, and status.
- Check whether an instrument is currently frozen during order execution.
- Reject orders for frozen instruments.

## Freeze Reasons

- `LINEUP_LOCK`
- `LIVE_MATCH`
- `POST_MATCH_SETTLEMENT`
- `ADMIN_HALT`
- `DATA_ISSUE`

## Boundaries

- The worker service may detect fixture events.
- This module decides whether trading is allowed for a given instrument.
- The API service and worker service must not bypass freeze checks.
