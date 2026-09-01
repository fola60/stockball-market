# Twitter Transfers

## Public Contract

This worker-owned domain converts transient Twitter post text into deterministic,
typed transfer signals. It does not fetch posts, persist data, schedule jobs, call an
LLM, scrape a browser, or read/write prices, orders, trades, positions, or cash.

Callers provide:

- A reviewed `TwitterSourceAccount`.
- A `PlayerResolution` produced by the parent Twitter canonical player resolver.
- Optional caller-resolved origin and destination `TeamReference` values.
- The post text.

`RuleBasedTransferClassifier.classify` returns a `TransferSignal` containing the
classification, canonical references, source category, source trust weight, base
confidence, adjusted confidence, aggregate-only flag, and matched rule names.

## Categories

`TransferStage` supports:

- `RUMOUR`: links, interest, targets, monitoring, or a possible move.
- `BID`: a formal bid or offer has been made or submitted.
- `NEGOTIATION`: talks, negotiations, or terms discussions.
- `AGREEMENT`: an agreement, deal, or personal terms have been agreed.
- `MEDICAL`: a medical is booked, underway, passed, or completed.
- `CONFIRMED`: an official signing, completed transfer, arrival, or new contract.
- `DENIED`: reports are denied, have no truth, or the player is not for sale.
- `FAILED`: the deal collapsed, talks broke down, a bid was rejected, or a medical failed.

`TransferTerms` distinguishes `PERMANENT`, `LOAN`, `CONTRACT_EXTENSION`, and
`UNKNOWN`. `TransferMovement` distinguishes `ARRIVAL`, `DEPARTURE`, `RETENTION`,
and `UNKNOWN`. Missing terms or teams remain unknown rather than being guessed.

## Trust And Resolution

Confidence is the rule's base confidence multiplied by the reviewed source trust
weight. Explicit uncertainty reduces positive confidence by 25 percent. Both values
remain visible in `TransferClassification`.

Fan sources are always `aggregate_only`, capped at `0.35`, and never actionable.
They may contribute only to a future aggregate attention metric. An actionable signal
requires one uniquely resolved canonical player, adjusted confidence of at least
`0.55`, no positive-evidence negation, and no ambiguous team reference. A missing team
is allowed because many credible early reports do not name both clubs; an ambiguous
team blocks lifecycle mutation.

Team resolution is deliberately outside this package. Callers may provide a canonical
UUID, an unresolved label, or candidate UUIDs marked `AMBIGUOUS`. The classifier never
extracts or invents a team identifier.

## Lifecycle

`TransferLifecycleStateMachine` applies actionable signals to one player lifecycle:

```text
RUMOUR -> BID -> NEGOTIATION -> AGREEMENT -> MEDICAL -> CONFIRMED
```

Real reporting may skip stages. Higher stages advance the lifecycle, while older or
same-stage evidence attaches without regression. `DENIED` and `FAILED` terminate any
non-terminal lifecycle. Terminal lifecycles are immutable; credible later evidence can
start a new cycle after a denial or failure. Conflicting destination, movement, or
loan/permanent/extension semantics start a distinct lifecycle instead of silently
overwriting the prior event.

Expiry is based on the latest actionable evidence:

- Rumour and bid: 14 days.
- Negotiation: 21 days.
- Agreement: 7 days.
- Medical: 5 days.
- Confirmed: 90 days.
- Denied and failed: 14 days.

An expired lifecycle is not updated; later actionable evidence creates a new one.
The package returns `CREATE`, `UPDATE`, `ATTACH`, or `IGNORE` decisions only. Persistence
and worker wiring are intentionally left to the parent integration.
