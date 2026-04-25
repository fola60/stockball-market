# Worker Ingestion Market Values Module

## Purpose

Ingests external player market values used for initial Stockball price seeding.

## Responsibilities

- Fetch or scrape player market-value data.
- Match external player records to canonical players.
- Store source, value, currency, and observed timestamp.
- Provide initial valuation anchors for `PLAYER_SHARE` instrument creation.

## V1 Source

Market value should be treated as a separate provider feed from squad/player identity unless the chosen football-data provider explicitly includes reliable player-level valuations.

Preferred order:

1. Licensed/commercial valuation provider or dataset with player-level values and stable IDs.
2. Manual/admin CSV import for development and early V1 seeding.
3. Transfermarkt-derived data only if we have a compliant source path, such as permission, a licensed provider, or an accepted internal manual workflow.

Do not make direct Transfermarkt scraping the default production ingestion path. It is attractive because it has familiar market values, but it creates avoidable licensing, scraping-fragility, and rate-limit risk.

## CSV Fallback Contract

The fallback importer should accept rows like:

```csv
source,source_player_id,source_url,display_name,date_of_birth,nationality,club,value,currency,observed_at
transfermarkt_manual,12345,https://www.transfermarkt.com/...,Bukayo Saka,2001-09-05,England,Arsenal,150000000,EUR,2026-04-25
```

`source_player_id` is preferred, but `source_url` plus identity fields is acceptable for manual imports. Values should be stored in minor-free decimal form with an explicit currency and observation timestamp.

## Matching

Market-value records must link through canonical `players.id`.

Matching order:

1. Existing provider reference for the value source.
2. Existing verified cross-provider reference.
3. Exact normalized identity match using name, date of birth, nationality, and club.
4. Manual review queue for ambiguous matches.

Never silently match on name alone. Premier League squads include duplicate or near-duplicate names, name spelling differences, initials, accents, and academy players with limited metadata.

## Storage

Store market values as observations, not as mutable player attributes:

```sql
player_market_value_observations (
    id uuid primary key,
    player_id uuid not null references players(id),
    source text not null,
    source_player_id text,
    value numeric(20, 4) not null,
    currency text not null,
    observed_at timestamptz not null,
    imported_at timestamptz not null,
    raw_payload jsonb not null default '{}'::jsonb
)
```

The seeding process should use the latest accepted market-value observation per player. After V1 seeding, market-value updates should not directly move live prices; they may be used for admin context or future reseeding policy.

## Boundaries

- Does not directly set live trading prices after V1 seeding.
- Does not decide price movement.
- Price movement after seeding belongs to executed trades in the trading engine.
