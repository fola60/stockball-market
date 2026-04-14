# Trading Engine Snapshots Module

## Purpose

Owns historical price records.

## Responsibilities

- Record price snapshots after every price-changing trade.
- Store asset ID, old price, new price, reason, related trade ID, and timestamp.
- Support price charts.
- Support admin debugging and audit trails.

## Boundaries

- Current price belongs to `assets`.
- Historical price records belong here.
- This module records what happened; it does not decide price movement.
