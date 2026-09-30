# Worker Ingestion Betting Markets Module

## Purpose

Ingests pre-match and live Bet365 match and player-market odds observations through an
explicitly enabled rendered Chrome session. This is the only supported Bet365 ingestion path.

These reads answer: "What do external betting markets currently imply?"

## Responsibilities

- Fetch pre-match odds from a rendered browser session.
- Discover the configured competition from the homepage and each rendered fixture URL.
- Refresh known event URLs during their configured live window without repeating discovery.
- Store stable market selections separately from append-only odds observations.
- Attach player participants to selections without encoding player names in market types.
- Preserve raw provider payloads for auditability.
- Normalize odds into decimal format.
- Derive implied probabilities where useful, while retaining the original quoted odds.
- Track provider rate limits, market availability, and stale snapshots.

## Current Scope

- Match result (`MATCH_RESULT_1X2`): `HOME`, `DRAW`, and `AWAY`.
- Player goalscorer, assist, score-or-assist, shots, shots on target, fouls committed,
  fouls drawn, and card markets.
- Decimal odds, implied probability, provider event ID, observed timestamp, and parsed page context.
- Website observations preserve team names and the Bet365 `D8/E...` event ID in raw data.
- Pre-match and live refreshes write the same normalized observation shape.

Only fully rendered player grids with recognizable semantic headings are parsed. Collapsed,
unavailable, or incomplete markets are skipped rather than guessed. The data model supports
multiple player participants for pair markets, but website parsing for pair markets remains
future work.

Lineups and match/player statistics remain outside this module and continue through fixture
and statistics ingestion.

## Website Discovery

The ingestion client uses a real rendered Chrome session because Bet365 navigation targets
are client-side hash routes and are not present as `href` values in saved HTML. The flow is:

1. Open `#/HO/` and use a direct competition link when one is visible.
2. Otherwise click `Football`, then select the configured competition from the football hub.
3. Read the resulting competition URL and parse rendered pre-match fixture rows.
4. Exclude fixtures at or inside the configured pre-match cutoff.
5. Re-open the competition and click each remaining team-vs-team row.
6. Read the resulting `#/.../D8/E{event_id}/...` URL.
7. Parse the exact `Full Time Result` market and any expanded, supported player grids.
8. Normalize fractional odds to decimal and persist a quote against its stable selection.

Discovery and parsing use semantic labels and relationships between dates, kickoff times,
team names, and odds. Do not depend on Bet365's generated CSS class names; those identifiers
change independently of the page's betting-market structure.

## Live Refresh

The pre-match crawl stores each event URL and parsed kickoff timestamp in selection metadata.
The live scheduler runs every minute by default, queries for events whose scheduled kickoff is
within the configured live window, and opens only those known event URLs. It parses whatever
supported markets are currently available; suspended or absent markets are skipped.

Live ingestion does not require score or match-phase data. Those facts may explain an odds
change, but the betting strategy consumes the bookmaker's current implied probability and its
movement directly. A pre-match discovery run must happen before a fixture can be live-refreshed.

```bash
STOCKBALL_BET365_SCHEDULE_ENABLED=false
STOCKBALL_BET365_LIVE_SCHEDULE_ENABLED=false
STOCKBALL_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES=1
STOCKBALL_BET365_LIVE_EVENT_WINDOW_MINUTES=180
STOCKBALL_BET365_WEBSITE_URL=https://www.bet365.com/#/HO/
STOCKBALL_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS=5
STOCKBALL_BET365_COMPETITION_NAME=Premier League
STOCKBALL_BET365_MAX_MATCHES=20
STOCKBALL_BET365_PRE_MATCH_CUTOFF_MINUTES=5
STOCKBALL_BET365_BROWSER_ENABLED=true
```

Run the ingestion manually with:

```bash
scripts/local-ingestion.sh bet365 --league PL --max-matches 20
```

The worker CLI exposes both modes:

```bash
stockball-worker ingest-bet365-odds --mode PRE_MATCH --league PL --max-matches 20
stockball-worker ingest-bet365-odds --mode LIVE --max-matches 20
```

To exercise the same browser client and inspect all supported results without writing to the database,
run from `services/worker`:

```bash
python3 -m scripts.probe_bet365_search --league PL --max-matches 5
```

Worker ingestion always uses an isolated temporary browser profile and does not access a
personal Chrome profile. Both the 15-minute discovery scheduler and one-minute live scheduler
remain independently opt-in. Keep live navigation time below its schedule interval to avoid a
queue backlog.

Website event IDs are not FBref fixture IDs. Website observations therefore remain
unlinked (`fixture_id = NULL`) until a separate canonical fixture-matching step is added.

## Storage Shape

- `betting_market_selections` identifies a stable provider event, scope, market type,
  period, outcome, and optional threshold line.
- `betting_market_selection_players` links one or more canonical players to a selection
  when names resolve unambiguously; the provider player name is retained regardless.
- `betting_market_observations` stores each observed odds quote and raw provider payload.
- Duplicate quotes are prevented per selection and `observed_at`; repeated crawls at new
  times intentionally create new observations so odds movement remains queryable.

Thresholds are data (`line = 0.5`, `1.5`, and so on), not new market-type values. Market,
period, outcome, scope, and participant role values are constrained by the database and
mirrored by typed worker enums.

## Usage

- Player-linked betting observations feed the `BETTING_MARKET_VALUE` synthetic trader engine.
- Betting observations may support admin context around fixtures and player demand.
- Betting observations should be treated as external facts, not Stockball prices.

## Boundaries

- Does not execute trades.
- Does not directly mutate Stockball instrument prices.
- Does not decide synthetic trader orders directly.
- Does not replace executed Stockball trades as the source of price movement.
- Must not scrape or store odds from sources that prohibit automated use.
