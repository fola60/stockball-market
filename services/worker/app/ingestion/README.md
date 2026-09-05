# Worker Ingestion Module

## Purpose

Owns all external data intake.

Ingestion answers: "What did the outside world say?"

## Responsibilities

- Fetch or scrape external data.
- Normalize provider-specific data into internal records.
- Store raw or normalized provider observations.
- Handle provider IDs, rate limits, retries, and failures.
- Keep provider-specific code away from trading and bot strategy modules.

## Submodules

- `players`: Premier League player identity and squad data.
- `market_values`: external player market-value data.
- `fixtures`: fixture, lineup, and match-status data.
- `stats`: player performance data from external providers.
- `betting_markets`: opt-in rendered-page Bet365 pre-match discovery and live odds snapshots.
- `social/twitter`: opt-in approved-X-API injury episodes and availability observations.
- Future broader `social`: social mention and sentiment data from approved providers.
- Future `news`: football news and transfer-rumor data.
- `fbref`: isolated FBref client, parser, raw-page cache, and provider service.
- `fetch`: provider-neutral, host-allowlisted content-fetching boundary for approved URLs.
- `providers`: shared provider exports.

## V1 Player Universe And Valuation Approach

Use a provider-backed ingestion flow rather than one-off seed SQL for the Premier League player universe. The same job must be safe to rerun because player club and league membership changes over time.

Current source split:

- Player identity, squads, fixtures, and player stat tables: use FBref as the current provider with `provider = 'FBREF'`.
- Market value: do not assume the squad provider will supply usable player market values. Most football fixture/stat APIs do not provide Transfermarkt-style market valuations. Use a separate market-value provider or licensed dataset if we need real transfer-market-style valuations.
- Development fallback: allow a manually curated CSV for market values so local seeding can proceed without scraping or committing to a paid provider. The CSV should include source, source player ID or source URL, value, currency, observed date, and enough identity fields to reconcile to a canonical player.

Avoid building against direct Transfermarkt scraping as the default path. Transfermarkt is the obvious market-value reference, but scraping creates operational and licensing risk. If Transfermarkt-derived values are used, prefer a licensed provider, explicit permission, or an internal/manual import path that records the source and observation date.

FBref is also HTML-scraped and governed by restrictive Sports Reference terms and bot-traffic guidance. Keep the provider isolated under `ingestion/fbref`, cache fetched pages, use conservative request cadence, and be ready to replace it with a licensed provider.

## Provider Identity Strategy

Do not use one external provider ID as the Stockball player ID. Stockball should maintain a canonical `players.id`, then attach provider references to that player.

The current schema stores `provider` and `provider_player_id` on `players` and augments that with `player_provider_refs`:

```sql
player_provider_refs (
    player_id uuid not null references players(id),
    provider text not null,
    provider_player_id text not null,
    provider_url text,
    confidence numeric(4, 3),
    is_primary boolean not null default false,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    raw_identity jsonb not null default '{}'::jsonb,
    unique (provider, provider_player_id)
)
```

Reconciliation order:

1. Match by an existing `(provider, provider_player_id)` reference.
2. Match by a verified cross-provider mapping if a provider supplies one.
3. Match deterministically by normalized name, date of birth, nationality, and current club.
4. Queue ambiguous matches for admin review instead of guessing.

Store raw provider payloads or normalized observations for auditability. Canonical player fields should represent Stockball's current best view; provider observations should remain available when later imports disagree.

## Rerunnable Jobs

Player and valuation ingestion should be idempotent.

- A Premier League squad sync should upsert canonical players, update current club/position metadata, mark provider refs as seen, and record whether the player is currently in the Premier League universe.
- A player leaving the Premier League should not be deleted. Mark them inactive/out-of-universe and let the instrument policy decide whether to keep trading, freeze, or delist.
- A market-value sync should append a new observed value when the provider value or observation timestamp changes. It should not overwrite history.
- Instrument creation should be a separate seeding step that reads canonical players plus the latest accepted market value.

## Betting Market Reads

The Bet365 adapter ingests pre-match and live match/player-market snapshots through rendered
page discovery and known-event refreshes. Additional market enum values require a schema and
provider review.

Scope:

- Match-level 1X2 and supported expanded player grids are implemented. Other match markets and collapsed player grids remain future work.
- Team and player prop markets only if the provider licensing and coverage are clear.
- Bookmaker or exchange name, market type, selection, odds, currency where applicable, observed timestamp, and fixture/provider IDs.
- Derived implied probabilities after removing or recording bookmaker margin.

Usage:

- Player-linked betting market observations inform `BETTING_MARKET_VALUE` bot decisions.
- Betting market observations must not directly mutate Stockball instrument prices in V1.
- Any future direct use in pricing would require a separate product decision and trading-engine rule change.

Provider constraints:

- Prefer licensed odds APIs or exchange APIs with explicit permission for storage and product use.
- Preserve raw payloads and provider IDs because odds can move quickly and may be disputed later.
- Pre-match discovery is periodic; live refresh is independently opt-in and defaults to one minute.

## Boundaries

- Does not execute trades.
- Does not directly change instrument prices.
- Does not decide bot trades.
- Writes facts and observations that other modules can interpret.

## Twitter Injury Intelligence

The Twitter injury pipeline is rules-based, manually source-curated, and disabled by default.
It stores no post text, rejects unregistered authors, records ambiguous player matches
without guessing, and exposes compact availability observations without connecting them
to strategy or execution. See `social/twitter/README.md` for the full retrieval, cursor,
source trust, classification, episode, recurrence, expiration, policy, and run contract.
