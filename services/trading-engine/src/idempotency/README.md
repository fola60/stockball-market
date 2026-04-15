# Trading Engine Idempotency Module

## Purpose

Prevents retry-sensitive commands from executing more than once.

Idempotency means the same request can be retried safely without duplicating the action.

## Responsibilities

- Store idempotency keys for executed commands.
- Detect duplicate order, top-up, admin adjustment, freeze, or unfreeze commands.
- Return the previous result for a duplicate request where appropriate.
- Protect against network retries and worker job retries.

## Examples

- A user buy request times out and the API retries it.
- A bot trade job retries after a worker crash.
- A weekly top-up job is rerun.

In each case, the command should only apply once.

## Boundaries

- Does not decide business validity.
- Does not mutate cash, positions, or prices directly.
- Must be used by modules that execute non-repeatable actions.
