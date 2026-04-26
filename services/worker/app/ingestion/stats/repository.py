from __future__ import annotations

from uuid import UUID

import psycopg2
from psycopg2.extras import Json

from .models import ApiFootballPlayerStat


class PostgresPlayerStatsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_player_stats(self, observations: list[ApiFootballPlayerStat]) -> tuple[int, int]:
        if not observations:
            return 0, 0

        matched_players = 0
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                for observation in observations:
                    fixture_id = _get_fixture_id(
                        cursor,
                        observation.provider,
                        observation.provider_fixture_id,
                    )
                    player_id = _get_player_id(
                        cursor,
                        observation.provider,
                        observation.provider_player_id,
                    )
                    if player_id is not None:
                        matched_players += 1
                    cursor.execute(
                        """
                        INSERT INTO player_stat_observations (
                            fixture_id,
                            player_id,
                            provider,
                            provider_fixture_id,
                            provider_player_id,
                            team_provider_id,
                            team_name,
                            display_name,
                            rating,
                            stats,
                            raw_payload,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                        )
                        ON CONFLICT (provider, provider_fixture_id, provider_player_id)
                        DO UPDATE
                        SET
                            fixture_id = EXCLUDED.fixture_id,
                            player_id = EXCLUDED.player_id,
                            team_provider_id = EXCLUDED.team_provider_id,
                            team_name = EXCLUDED.team_name,
                            display_name = EXCLUDED.display_name,
                            rating = EXCLUDED.rating,
                            stats = EXCLUDED.stats,
                            raw_payload = EXCLUDED.raw_payload,
                            observed_at = now(),
                            updated_at = now()
                        """,
                        (
                            fixture_id,
                            player_id,
                            observation.provider,
                            observation.provider_fixture_id,
                            observation.provider_player_id,
                            observation.team_provider_id,
                            observation.team_name,
                            observation.display_name,
                            observation.rating,
                            Json(dict(observation.stats)),
                            Json(dict(observation.raw_payload)),
                        ),
                    )
            connection.commit()

        return len(observations), matched_players


def _get_fixture_id(cursor: object, provider: str, provider_fixture_id: str) -> UUID | None:
    cursor.execute(
        """
        SELECT id::text
        FROM fixtures
        WHERE provider = %s
          AND provider_fixture_id = %s
        """,
        (provider, provider_fixture_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))


def _get_player_id(cursor: object, provider: str, provider_player_id: str) -> UUID | None:
    cursor.execute(
        """
        SELECT id::text
        FROM players
        WHERE provider = %s
          AND provider_player_id = %s
        """,
        (provider, provider_player_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return UUID(str(row[0]))
