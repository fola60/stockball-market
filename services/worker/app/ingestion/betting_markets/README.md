# Worker Ingestion Betting Markets Module

## Purpose

Ingests pre-match Bet365 1X2 (home/draw/away) odds observations through an explicitly
enabled rendered Chrome session. This is the only supported Bet365 ingestion path.

These reads answer: "What did external betting markets imply before the match?"

## Responsibilities

- Fetch pre-match odds from a rendered browser session.
- Discover the configured competition from the homepage and each rendered fixture URL.
- Store fixture IDs, market types, selections, odds, source, and observed timestamps.
- Preserve raw provider payloads for auditability.
- Normalize odds into decimal format.
- Derive implied probabilities where useful, while retaining the original quoted odds.
- Track provider rate limits, market availability, and stale snapshots.

## Current Scope

- Pre-match match-result (`1X2`) selections only: `HOME`, `DRAW`, and `AWAY`.
- Decimal odds, implied probability, provider event ID, observed timestamp, and parsed page context.
- Website observations preserve team names and the Bet365 `D8/E...` event ID in raw data.

Lineups, player props, and match/player statistics are intentionally out of scope. They
need a separately licensed provider and should continue through fixture/stat ingestion.

## Website Discovery

The ingestion client uses a real rendered Chrome session because Bet365 navigation targets
are client-side hash routes and are not present as `href` values in saved HTML. The flow is:

1. Open `#/HO/` and use a direct competition link when one is visible.
2. Otherwise click `Football`, then select the configured competition from the football hub.
3. Read the resulting competition URL and parse rendered pre-match fixture rows.
4. Exclude fixtures at or inside the configured pre-match cutoff.
5. Re-open the competition and click each remaining team-vs-team row.
6. Read the resulting `#/.../D8/E{event_id}/...` URL.
7. Parse only the exact `Full Time Result` market and normalize fractional odds to decimal.

Discovery and parsing use semantic labels and relationships between dates, kickoff times,
team names, and odds. Do not depend on Bet365's generated CSS class names; those identifiers
change independently of the page's betting-market structure.

```bash
STOCKBALL_BET365_SCHEDULE_ENABLED=false
STOCKBALL_BET365_POLICY_ACKNOWLEDGED=true
STOCKBALL_BET365_WEBSITE_URL=https://www.bet365.com/#/HO/
STOCKBALL_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS=5
STOCKBALL_BET365_COMPETITION_NAME=Premier League
STOCKBALL_BET365_MAX_MATCHES=20
STOCKBALL_BET365_PRE_MATCH_CUTOFF_MINUTES=5
STOCKBALL_BET365_BROWSER_ENABLED=true
# Optional persistent, dedicated profile. Omit both values for an isolated temporary profile.
STOCKBALL_BET365_BROWSER_USER_DATA_DIR="$HOME/Library/Application Support/Stockball Market/Chrome"
STOCKBALL_BET365_BROWSER_PROFILE_DIRECTORY=Default
```

Run the ingestion manually with:

```bash
scripts/local-ingestion.sh bet365 --league PL --max-matches 20
```

To exercise the same browser client and inspect normalized results without writing to the
database, run from `services/worker`:

```bash
python3 -m scripts.test_bet365_search --league PL --max-matches 5
```

Website access is disabled until the deployment owner explicitly acknowledges that the
access, storage, and product use have been reviewed. Temporary browser profiles require no
personal Chrome access. If a dedicated persistent profile is configured, that profile must
not already be open because Chrome locks its user-data directory. The 15-minute scheduler
remains opt-in and should only be enabled after validating access and crawl duration.

Website event IDs are not FBref fixture IDs. Website observations therefore remain
unlinked (`fixture_id = NULL`) until a separate canonical fixture-matching step is added.

## Candidate Markets

- Match result: home/draw/away.
- Draw no bet.
- Asian handicap.
- Total goals.
- Both teams to score.
- Correct score.
- Future player props if licensing and coverage are clear.

## Usage

- Betting observations may feed future market-aware synthetic trader signals.
- Betting observations may support admin context around fixtures and player demand.
- Betting observations should be treated as external facts, not Stockball prices.

## Boundaries

- Does not execute trades.
- Does not directly mutate Stockball instrument prices.
- Does not decide synthetic trader orders directly.
- Does not replace executed Stockball trades as the source of price movement.
- Must not scrape or store odds from sources that prohibit automated use.
