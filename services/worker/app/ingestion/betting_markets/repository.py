from __future__ import annotations

from datetime import datetime, timedelta

from psycopg2.extras import Json

from app.database import connection as pooled_connection

from .models import (
    BET365_PROVIDER,
    MATCH_RESULT_1X2,
    Bet365DiscoveredFixture,
    BettingMarketObservation,
    BettingMarketSelection,
)


class PostgresBettingMarketRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_observations(self, observations: list[BettingMarketObservation]) -> int:
        if not observations:
            return 0
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                for observation in observations:
                    selection_id = _upsert_selection(cursor, observation.selection)
                    _replace_participants(cursor, selection_id, observation.selection)
                    cursor.execute(
                        """
                        INSERT INTO betting_market_observations (
                            selection_id,
                            decimal_odds,
                            implied_probability,
                            observed_at,
                            source_url,
                            raw_payload
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (selection_id, observed_at)
                        DO UPDATE SET
                            decimal_odds = EXCLUDED.decimal_odds,
                            implied_probability = EXCLUDED.implied_probability,
                            source_url = EXCLUDED.source_url,
                            raw_payload = EXCLUDED.raw_payload,
                            updated_at = now()
                        """,
                        (
                            selection_id,
                            observation.decimal_odds,
                            observation.implied_probability,
                            observation.observed_at,
                            observation.source_url,
                            Json(dict(observation.raw_payload)),
                        ),
                    )
            connection.commit()
        return len(observations)

    def list_live_event_pages(
        self,
        as_of: datetime,
        *,
        event_window_minutes: int,
        limit: int,
    ) -> tuple[Bet365DiscoveredFixture, ...]:
        window_start = as_of - timedelta(minutes=event_window_minutes)
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH latest_event_pages AS (
                        SELECT DISTINCT ON (selection.provider_event_id)
                            selection.provider_event_id,
                            selection.raw_payload ->> 'home_team' AS home_team,
                            selection.raw_payload ->> 'away_team' AS away_team,
                            selection.raw_payload ->> 'date_label' AS date_label,
                            selection.raw_payload ->> 'kickoff_time_label' AS kickoff_time_label,
                            (selection.raw_payload ->> 'kickoff_at')::timestamptz AS kickoff_at,
                            observation.source_url,
                            observation.observed_at
                        FROM betting_market_selections AS selection
                        JOIN betting_market_observations AS observation
                            ON observation.selection_id = selection.id
                        WHERE selection.provider = %s
                          AND selection.market_type = %s
                          AND selection.raw_payload ->> 'kickoff_at' IS NOT NULL
                          AND observation.source_url IS NOT NULL
                        ORDER BY
                            selection.provider_event_id,
                            observation.observed_at DESC,
                            observation.id DESC
                    )
                    SELECT
                        provider_event_id,
                        home_team,
                        away_team,
                        date_label,
                        kickoff_time_label,
                        kickoff_at,
                        source_url
                    FROM latest_event_pages
                    WHERE kickoff_at > %s
                      AND kickoff_at <= %s
                    ORDER BY kickoff_at, provider_event_id
                    LIMIT %s
                    """,
                    (
                        BET365_PROVIDER,
                        MATCH_RESULT_1X2,
                        window_start,
                        as_of,
                        limit,
                    ),
                )
                rows = cursor.fetchall()

        return tuple(
            Bet365DiscoveredFixture(
                provider_event_id=str(row[0]),
                home_team=str(row[1]),
                away_team=str(row[2]),
                date_label=None if row[3] is None else str(row[3]),
                kickoff_time_label=None if row[4] is None else str(row[4]),
                kickoff_at=row[5],
                source_url=str(row[6]),
            )
            for row in rows
        )


def _upsert_selection(cursor: object, selection: BettingMarketSelection) -> str:
    cursor.execute(
        """
        INSERT INTO betting_market_selections (
            fixture_id,
            provider,
            provider_event_id,
            fixture_provider_id,
            market_scope,
            market_type,
            period,
            outcome_type,
            line,
            canonical_selection_key,
            provider_market_label,
            provider_selection_label,
            raw_payload
        ) VALUES (
            (SELECT id FROM fixtures WHERE provider_fixture_id = %s LIMIT 1),
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (provider, provider_event_id, canonical_selection_key)
        DO UPDATE SET
            fixture_id = COALESCE(EXCLUDED.fixture_id, betting_market_selections.fixture_id),
            fixture_provider_id = COALESCE(
                EXCLUDED.fixture_provider_id,
                betting_market_selections.fixture_provider_id
            ),
            market_scope = EXCLUDED.market_scope,
            market_type = EXCLUDED.market_type,
            period = EXCLUDED.period,
            outcome_type = EXCLUDED.outcome_type,
            line = EXCLUDED.line,
            provider_market_label = EXCLUDED.provider_market_label,
            provider_selection_label = EXCLUDED.provider_selection_label,
            raw_payload = EXCLUDED.raw_payload,
            updated_at = now()
        RETURNING id::text
        """,
        (
            selection.fixture_provider_id,
            selection.provider,
            selection.provider_event_id,
            selection.fixture_provider_id,
            selection.market_scope.value,
            selection.market_type,
            selection.period.value,
            selection.outcome_type.value,
            selection.line,
            selection.canonical_selection_key,
            selection.provider_market_label,
            selection.provider_selection_label,
            Json(dict(selection.raw_payload)),
        ),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("betting market selection upsert did not return an id")
    return str(row[0])


def _replace_participants(
    cursor: object,
    selection_id: str,
    selection: BettingMarketSelection,
) -> None:
    cursor.execute(
        "DELETE FROM betting_market_selection_players WHERE selection_id = %s",
        (selection_id,),
    )
    for position, participant in enumerate(selection.participants):
        cursor.execute(
            """
            INSERT INTO betting_market_selection_players (
                selection_id,
                participant_position,
                player_id,
                provider_player_name,
                participant_role
            ) VALUES (
                %s,
                %s,
                (
                    SELECT candidate.id
                    FROM (
                        SELECT id, count(*) OVER () AS candidate_count
                        FROM players
                        WHERE lower(display_name) = lower(%s)
                    ) AS candidate
                    WHERE candidate.candidate_count = 1
                ),
                %s,
                %s
            )
            """,
            (
                selection_id,
                position,
                participant.provider_player_name,
                participant.provider_player_name,
                participant.role.value,
            ),
        )
