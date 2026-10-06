# FotMob player match ratings

Final Premier League match ratings, on FotMob's native 0–10 scale. This module does not
change synthetic-trader or trading-engine inputs. `player_match_ratings` stores one
appearance per provider match/player. `player_season_ratings` provides the unweighted
mean of published ratings, appearance counts, minutes and latest match date.
Missing ratings remain NULL; unused substitutes are excluded.

## Run

```sh
scripts/local-ingestion.sh fotmob --season 2025 --backfill
scripts/local-ingestion.sh fotmob --season 2026 --backfill
```

Seasons are start years: 2025 means 2025/26. The default league is FotMob 47
(Premier League), not FBref 9. A backfill covers every finished match; future,
cancelled, abandoned and awarded matches are not assigned ratings. Repeating a
backfill resumes missing matches. Add `--refresh` to re-fetch completed matches,
`--max-matches N` to bound a batch, or `--archive-dir /path/to/archive` to reuse
previously downloaded JSON documents. Use `--refresh` to replace incomplete or
invalid archived documents. The archive is used only for backfills;
scheduled runs always retrieve current documents.

## Scheduled ingestion

Apply migrations 0030 and 0031, deploy the ingestion worker and scheduler, then enable
`STOCKBALL_FOTMOB_SCHEDULE_ENABLED=true` in their Compose environment. The admin
Processes list exposes **FotMob player ratings**, with the existing start/pause controls.
The scheduler creates an `INGEST_FOTMOB_RATINGS` run every 15 minutes, routed to the
ingestion queue. Only one scheduled FotMob run can be in flight. Batches contain up
to 40 completed matches and follow the current season each July.

Every poll rediscovers the complete season fixture list. A match becomes eligible
15 minutes after it is first observed as finished. Previously completed matches
from the last 48 hours are revisited at six-hour intervals for corrections. Missing
or failed matches remain eligible regardless of age. Retry ordering places never
attempted matches first, so a failing match cannot starve the rest of the backlog.
The request interval defaults to two seconds and is configurable with
`STOCKBALL_FOTMOB_REQUEST_INTERVAL_SECONDS`.

## Source and identity checks

Season pages expose the complete fixture catalogue in `__NEXT_DATA__`. Match data
comes from `/api/data/matchDetails?matchId=...`. A match page's URL fragment is not
sent in HTTP requests: its server-rendered HTML can describe a different meeting.
Never ingest that HTML as the historical match identified by the fragment.

The parser validates match ID, competition, kickoff, home/away identities, final
status and complete starter coverage before checkpointing a match. Raw successful
responses are retained in `provider_raw_documents`, keyed by source and content hash.
Rows are upserted transactionally with their match checkpoint; replays cannot add
duplicate appearances. Failed responses are recorded in `fotmob_matches.last_error`.

Player linking reuses the market-value matcher against canonical FBref players:
existing reviewed provider reference, then normalized name plus date of birth,
normalized name plus club, and finally a unique name across source and candidate
identities. It shares the same name and club alias normalization and confidence
scores. For unresolved name variants, the ingester retrieves each FotMob player
profile once and compares its birth date against the canonical player's date of
birth, including dates from reviewed market-value provider references. A variant
needs a shared name token, the same birth date, and the same club to link.
Ambiguous and unmatched identities are recorded in
`fotmob_player_identity_matches` for review, with their provider IDs and all
appearances preserved. Earlier automatic name-only references are rechecked.
Reviewed references are retained. No players, instruments or prices are created.
Historical players absent from the current canonical roster remain queryable by
FotMob ID. No cross-provider fixture ID is guessed.

## Verify coverage

```sql
SELECT season, count(*) AS fixtures,
       count(*) FILTER (WHERE finished) AS finished,
       count(*) FILTER (WHERE finished AND ratings_fetched_at IS NOT NULL) AS ingested
FROM fotmob_matches GROUP BY season ORDER BY season;

SELECT season, count(*) AS appearances, count(rating) AS rated,
       count(player_id) AS linked
FROM player_match_ratings r JOIN fotmob_matches m ON m.match_id = r.provider_match_id
GROUP BY season ORDER BY season;
```

Provider response formats are not a versioned API contract. Schema changes fail
closed and leave a visible pending match instead of fabricating a rating.
