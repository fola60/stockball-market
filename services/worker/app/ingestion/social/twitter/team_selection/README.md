# Twitter Team Selection Intelligence

## Boundary

This package is a pure, worker-owned interpretation domain. It receives transient post
text plus an already reviewed `TwitterSourceAccount`; it does not retrieve posts,
persist records, schedule jobs, call the trading engine, or mutate prices, orders,
trades, positions, or cash.

The implementation is deterministic. It uses explicit rules, reviewed exact aliases,
and immutable dataclasses. It does not use an LLM, browser automation, fuzzy identity
matching, follower counts, or engagement metrics.

## Public Contract

`RuleBasedTeamSelectionClassifier.classify(...)` returns a
`TeamSelectionClassification` containing zero or more `TeamSelectionSignal` records.
One post may produce multiple signals, such as a lineup starter who is also captain or
is playing in a changed role.

Each signal exposes:

- `event_kind`: expected starter, lineup starter, bench, squad inclusion/exclusion,
  rested/rotated, positional-role change, captaincy, or goalkeeper change.
- `evidence_phase`: `PRE_MATCH_CLAIM` or `CONFIRMED_OFFICIAL`.
- `confidence`, `source_account_kind`, and `source_trust_weight`.
- `observed_at` and `expires_at`.
- `actionable` and `aggregate_only`.
- deterministic matched rules and an extracted positional role when applicable.

`TeamSelectionInterpreter.assess(...)` adds canonical identity safety. It composes the
existing exact `PlayerResolver` with this package's exact `TeamResolver`. A signal is
actionable only when both player and team resolve uniquely. Ambiguous or unresolved
identities remain visible in the assessment but cannot become actionable.

## Trust And Confirmation

Only `OFFICIAL_CLUB` and `OFFICIAL_LEAGUE` sources can emit
`CONFIRMED_OFFICIAL`. The same lineup wording from a player-owned or curated journalist
source remains a pre-match claim. Confidence is the event baseline multiplied by the
reviewed source trust weight, with reductions for pre-match and uncertain language.

Fan accounts are always `aggregate_only`, capped at `0.35`, and non-actionable. Disabled
sources are also non-actionable. This package does not aggregate fan claims; a future
repository may aggregate these low-trust signals without promoting an individual fan
post to an event.

## Rules And Expiry

Rules cover explicit phrases including `expected to start`, `starts`, `starting XI`,
`on the bench`, `named in the squad`, `not selected`, `rested`, `deployed as`,
`named captain`, and `starts in goal`. Starter and bench negations suppress their
corresponding matches. Uncertain terms such as `reportedly`, `could`, `may`, and
`unconfirmed` reduce confidence.

When fixture kickoff is known, pre-match claims expire at kickoff and confirmed
official events expire four hours after kickoff. Without fixture context, claims expire
after 12 hours and official confirmations after eight hours. The output is context for
future ingestion persistence and bot reads; it is not itself a trade decision.
