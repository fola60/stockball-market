# Shared Schemas

## Purpose

Stores shared JSON schemas or schema fragments used across service contracts.

## Responsibilities

- Define common payload shapes.
- Define shared enums such as order side, asset status, trade reason, and ledger reason.
- Reduce drift between API, worker, and trading-engine contracts.

## Boundaries

- Schemas do not contain service behavior.
- Services still own validation and business rules.
