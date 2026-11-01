from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection

from .models import TEAM_INDEX_KIND, RuleFund, TeamFund, TeamRoster
from .rules import ODDS_WINDOW_DAYS, RULE_INDEX_KIND, SOCIAL_WINDOW_DAYS, LeagueFacts, PlayerFacts


class IndexFundRepository(Protocol):
    def team_rosters(self, season: int) -> list[TeamRoster]: ...

    def team_funds(self) -> list[TeamFund]: ...

    def league_facts(self, season: int) -> LeagueFacts: ...

    def rule_funds(self) -> list[RuleFund]: ...


def _number(table: str, stat: str) -> str:
    """Sum of one FBref stat across a player's rows in one table, ignoring non-numbers."""
    return (
        f"SUM(CASE WHEN o.stat_type = '{table}' AND jsonb_typeof(o.stats -> '{stat}') = 'number'"
        f" THEN (o.stats ->> '{stat}')::numeric END)"
    )


# Every listed current-season player who can trade, with what the rules rank them by. Halted
# players (those leaving the league) are left out, as for team funds.
_LEAGUE_FACTS_QUERY = f"""
WITH live AS (
    SELECT i.id AS instrument_id, i.current_price, i.reference_price, p.id AS player_id,
           p.club, NULLIF(split_part(COALESCE(p.position, ''), ',', 1), '') AS position,
           CASE WHEN p.metadata ->> 'age' ~ '^[0-9]+'
                THEN substring(p.metadata ->> 'age' FROM '^[0-9]+')::int END AS age,
           NULLIF(split_part(COALESCE(p.metadata ->> 'nationality', ''), ' ', 2), '')
               AS nationality
    FROM instruments AS i
    JOIN players AS p ON p.id = i.player_id
    WHERE i.instrument_type = 'PLAYER_SHARE'
      AND i.trading_status <> 'DELISTED'
      AND p.club IS NOT NULL
      AND COALESCE(p.metadata ->> 'season', '') = %(season_text)s
      AND NOT EXISTS (
          SELECT 1 FROM instrument_freezes AS f
          WHERE f.instrument_id = i.id AND f.released_at IS NULL AND f.reason <> 'MATCH_DAY'
      )
),
market_value AS (
    SELECT DISTINCT ON (player_id) player_id, value
    FROM player_market_value_observations
    WHERE player_id IN (SELECT player_id FROM live)
    ORDER BY player_id, observed_at DESC
),
stats AS (
    SELECT o.player_id,
           {_number('standard', 'minutes')} AS minutes,
           {_number('standard', 'games')} AS games,
           {_number('standard', 'goals_pens')} AS non_penalty_goals,
           {_number('standard', 'assists')} AS assists,
           {_number('keeper', 'gk_minutes')} AS keeper_minutes
    FROM player_stat_observations AS o
    WHERE o.provider = 'FBREF' AND o.season = %(season)s
      AND o.player_id IN (SELECT player_id FROM live)
    GROUP BY o.player_id
),
-- FotMob's match data runs later into the season than FBref's tables and has chances created,
-- which FBref no longer publishes.
fotmob AS (
    SELECT r.player_id,
           SUM(COALESCE(r.minutes_played, 0)) AS minutes,
           COUNT(*) FILTER (WHERE COALESCE(r.minutes_played, 0) > 0) AS games,
           SUM(COALESCE(chances.created, 0)) AS chances_created
    FROM player_match_ratings AS r
    JOIN fotmob_matches AS m ON m.match_id = r.provider_match_id
    LEFT JOIN LATERAL (
        SELECT SUM((g -> 'stats' -> 'Chances created' -> 'stat' ->> 'value')::numeric) AS created
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(r.raw_payload -> 'stats') = 'array'
                 THEN r.raw_payload -> 'stats' ELSE '[]'::jsonb END
        ) AS g
        WHERE jsonb_typeof(g -> 'stats' -> 'Chances created' -> 'stat' -> 'value') = 'number'
    ) AS chances ON true
    WHERE m.season = %(season)s AND r.player_id IN (SELECT player_id FROM live)
    GROUP BY r.player_id
),
recent_ratings AS (
    SELECT player_id, AVG(rating) AS recent_rating, COUNT(*) AS rated_appearances
    FROM (
        SELECT r.player_id, r.rating,
               row_number() OVER (PARTITION BY r.player_id ORDER BY m.kickoff_at DESC) AS n
        FROM player_match_ratings AS r
        JOIN fotmob_matches AS m ON m.match_id = r.provider_match_id
        WHERE m.season = %(season)s AND r.rating IS NOT NULL
          AND r.player_id IN (SELECT player_id FROM live)
    ) AS rated
    WHERE n <= 5
    GROUP BY player_id
),
odds AS (
    SELECT DISTINCT ON (sp.player_id)
           sp.player_id, o.implied_probability,
           CASE WHEN o.raw_payload ->> 'kickoff_at' ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T'
                THEN (o.raw_payload ->> 'kickoff_at')::timestamptz
                ELSE o.observed_at END AS kickoff_at
    FROM betting_market_selection_players AS sp
    JOIN betting_market_selections AS s ON s.id = sp.selection_id
    JOIN betting_market_observations AS o ON o.selection_id = s.id
    WHERE s.market_type = 'GOALSCORER' AND s.outcome_type = 'ANYTIME'
      AND s.period = 'FULL_MATCH' AND sp.participant_role = 'PRIMARY'
      AND sp.player_id IN (SELECT player_id FROM live)
    ORDER BY sp.player_id, 3 DESC, o.observed_at DESC
),
fresh_odds AS (
    SELECT player_id, implied_probability FROM odds
    WHERE kickoff_at >= (SELECT MAX(kickoff_at) FROM odds) - %(odds_window)s
),
social AS (
    SELECT DISTINCT ON (player_id)
           player_id, trusted_mention_count, credibility_weighted_sentiment, calculated_at
    FROM player_social_signal_snapshots
    WHERE lookback_seconds = 604800 AND player_id IN (SELECT player_id FROM live)
    ORDER BY player_id, calculated_at DESC
),
fresh_social AS (
    SELECT * FROM social
    WHERE calculated_at >= (SELECT MAX(calculated_at) FROM social) - %(social_window)s
)
SELECT live.instrument_id, live.club, live.current_price, live.position, live.age,
       live.nationality,
       COALESCE(market_value.value, live.reference_price * 1000000) AS valuation,
       -- Whichever source has seen more of the season.
       GREATEST(COALESCE(stats.minutes, 0), COALESCE(fotmob.minutes, 0)) AS minutes,
       GREATEST(COALESCE(stats.games, 0), COALESCE(fotmob.games, 0)) AS games,
       COALESCE(stats.non_penalty_goals, 0) AS non_penalty_goals,
       COALESCE(stats.assists, 0) AS assists,
       COALESCE(fotmob.chances_created, 0) AS chances_created,
       COALESCE(stats.keeper_minutes, 0) AS keeper_minutes,
       recent_ratings.recent_rating, COALESCE(recent_ratings.rated_appearances, 0)
           AS rated_appearances,
       fresh_odds.implied_probability AS goalscorer_probability,
       fresh_social.trusted_mention_count AS social_mentions,
       fresh_social.credibility_weighted_sentiment AS social_sentiment
FROM live
LEFT JOIN market_value USING (player_id)
LEFT JOIN stats USING (player_id)
LEFT JOIN fotmob USING (player_id)
LEFT JOIN recent_ratings USING (player_id)
LEFT JOIN fresh_odds USING (player_id)
LEFT JOIN fresh_social USING (player_id)
ORDER BY live.instrument_id
"""


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


class PostgresIndexFundRepository:
    """Read-only: index funds are created by the trading engine."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[RealDictCursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def team_rosters(self, season: int) -> list[TeamRoster]:
        """Each club's listed players in this season's league roster.

        Players halted for any reason but a match day (those who left the league, or a manual
        halt) stay out, so a fund never starts with a share that cannot trade for weeks.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT p.club, i.id AS instrument_id
                FROM instruments AS i
                JOIN players AS p ON p.id = i.player_id
                WHERE i.instrument_type = 'PLAYER_SHARE'
                  AND i.trading_status <> 'DELISTED'
                  AND p.club IS NOT NULL
                  AND COALESCE(p.metadata ->> 'season', '') = %(season)s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM instrument_freezes AS f
                      WHERE f.instrument_id = i.id
                        AND f.released_at IS NULL
                        AND f.reason <> 'MATCH_DAY'
                  )
                ORDER BY p.club, i.id
                """,
                {"season": str(season)},
            )
            rows = cursor.fetchall()
        rosters: dict[str, list[UUID]] = {}
        for row in rows:
            rosters.setdefault(str(row["club"]), []).append(UUID(str(row["instrument_id"])))
        return [TeamRoster(club, tuple(ids)) for club, ids in rosters.items()]

    def team_funds(self) -> list[TeamFund]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    fund.instrument_id,
                    i.symbol,
                    fund.club,
                    fund.cash_per_unit,
                    i.current_price,
                    member.constituent_instrument_id AS member_id,
                    EXISTS (
                        SELECT 1
                        FROM instrument_freezes AS f
                        WHERE f.instrument_id = member.constituent_instrument_id
                          AND f.released_at IS NULL
                          AND f.reason <> 'MATCH_DAY'
                    ) AS halted
                FROM index_funds AS fund
                JOIN instruments AS i ON i.id = fund.instrument_id
                LEFT JOIN index_constituents AS member
                    ON member.index_instrument_id = fund.instrument_id
                WHERE fund.index_kind = %(kind)s
                  AND i.trading_status <> 'DELISTED'
                ORDER BY fund.club, member.constituent_instrument_id
                """,
                {"kind": TEAM_INDEX_KIND},
            )
            rows = cursor.fetchall()
        funds: dict[UUID, dict] = {}
        for row in rows:
            fund_id = UUID(str(row["instrument_id"]))
            fund = funds.setdefault(
                fund_id,
                {"symbol": str(row["symbol"]), "club": str(row["club"]), "members": set(),
                 "halted": set(), "cash": str(row["cash_per_unit"]),
                 "price": str(row["current_price"])},
            )
            if row["member_id"] is not None:
                member = UUID(str(row["member_id"]))
                fund["members"].add(member)
                if row["halted"]:
                    fund["halted"].add(member)
        return [
            TeamFund(
                instrument_id=fund_id,
                symbol=fund["symbol"],
                club=fund["club"],
                members=frozenset(fund["members"]),
                halted_members=frozenset(fund["halted"]),
                cash_per_unit=fund["cash"],
                unit_price=fund["price"],
            )
            for fund_id, fund in funds.items()
        ]

    def league_facts(self, season: int) -> LeagueFacts:
        with self._cursor() as cursor:
            cursor.execute(
                _LEAGUE_FACTS_QUERY,
                {
                    "season": season,
                    "season_text": str(season),
                    "odds_window": timedelta(days=ODDS_WINDOW_DAYS),
                    "social_window": timedelta(days=SOCIAL_WINDOW_DAYS),
                },
            )
            rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT DISTINCT team_name
                FROM player_stat_observations
                WHERE provider = 'FBREF' AND season = %(season)s AND team_name IS NOT NULL
                """,
                {"season": season - 1},
            )
            previous = frozenset(str(row["team_name"]) for row in cursor.fetchall())
        players = tuple(
            PlayerFacts(
                instrument_id=UUID(str(row["instrument_id"])),
                club=str(row["club"]),
                price=Decimal(str(row["current_price"])),
                position=row["position"],
                age=row["age"],
                nationality=row["nationality"],
                valuation=_optional_float(row["valuation"]),
                minutes=int(row["minutes"]),
                games=int(row["games"]),
                non_penalty_goals=int(row["non_penalty_goals"]),
                assists=int(row["assists"]),
                chances_created=int(row["chances_created"]),
                keeper_minutes=int(row["keeper_minutes"]),
                recent_rating=_optional_float(row["recent_rating"]),
                rated_appearances=int(row["rated_appearances"]),
                goalscorer_probability=_optional_float(row["goalscorer_probability"]),
                social_mentions=(
                    None if row["social_mentions"] is None else int(row["social_mentions"])
                ),
                social_sentiment=_optional_float(row["social_sentiment"]),
            )
            for row in rows
        )
        return LeagueFacts(season=season, players=players, previous_season_clubs=previous)

    def rule_funds(self) -> list[RuleFund]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    fund.instrument_id,
                    i.symbol,
                    fund.rule_key,
                    fund.cash_per_unit,
                    i.current_price,
                    COALESCE(
                        (SELECT MAX(r.created_at) FROM index_fund_rebalances AS r
                         WHERE r.index_instrument_id = fund.instrument_id
                           AND r.kind = 'REBALANCE'),
                        fund.created_at
                    ) AS last_rebalanced_at,
                    member.constituent_instrument_id AS member_id,
                    member.shares_per_unit,
                    player.current_price AS member_price,
                    EXISTS (
                        SELECT 1
                        FROM instrument_freezes AS f
                        WHERE f.instrument_id = member.constituent_instrument_id
                          AND f.released_at IS NULL
                          AND f.reason <> 'MATCH_DAY'
                    ) AS halted
                FROM index_funds AS fund
                JOIN instruments AS i ON i.id = fund.instrument_id
                LEFT JOIN index_constituents AS member
                    ON member.index_instrument_id = fund.instrument_id
                LEFT JOIN instruments AS player ON player.id = member.constituent_instrument_id
                WHERE fund.index_kind = %(kind)s
                  AND i.trading_status <> 'DELISTED'
                ORDER BY fund.rule_key, member.constituent_instrument_id
                """,
                {"kind": RULE_INDEX_KIND},
            )
            rows = cursor.fetchall()
        funds: dict[UUID, dict] = {}
        for row in rows:
            fund_id = UUID(str(row["instrument_id"]))
            fund = funds.setdefault(
                fund_id,
                {"symbol": str(row["symbol"]), "rule_key": str(row["rule_key"]),
                 "members": set(), "halted": set(), "holdings": {},
                 "cash": str(row["cash_per_unit"]), "price": str(row["current_price"]),
                 "last": row["last_rebalanced_at"]},
            )
            if row["member_id"] is not None:
                member = UUID(str(row["member_id"]))
                fund["members"].add(member)
                fund["holdings"][member] = (
                    Decimal(str(row["shares_per_unit"])), Decimal(str(row["member_price"]))
                )
                if row["halted"]:
                    fund["halted"].add(member)
        return [
            RuleFund(
                instrument_id=fund_id,
                symbol=fund["symbol"],
                rule_key=fund["rule_key"],
                members=frozenset(fund["members"]),
                halted_members=frozenset(fund["halted"]),
                cash_per_unit=fund["cash"],
                unit_price=fund["price"],
                holdings=fund["holdings"],
                last_rebalanced_at=fund["last"],
            )
            for fund_id, fund in funds.items()
        ]
