from __future__ import annotations

import json
from uuid import UUID

import psycopg2
from psycopg2.extras import Json

from .models import ExternalPlayerStat


class PostgresPlayerStatsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_player_stats(self, observations: list[ExternalPlayerStat]) -> tuple[int, int]:
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
                            stat_type,
                            season,
                            competition,
                            source_url,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
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
                            stat_type = EXCLUDED.stat_type,
                            season = EXCLUDED.season,
                            competition = EXCLUDED.competition,
                            source_url = EXCLUDED.source_url,
                            observed_at = now(),
                            updated_at = now()
                        """,
                        (
                            None if fixture_id is None else str(fixture_id),
                            None if player_id is None else str(player_id),
                            str(observation.provider),
                            str(observation.provider_fixture_id),
                            str(observation.provider_player_id),
                            None if observation.team_provider_id is None else str(observation.team_provider_id),
                            None if observation.team_name is None else str(observation.team_name),
                            str(observation.display_name),
                            observation.rating,
                            Json(dict(observation.stats), dumps=_json_dumps),
                            Json(dict(observation.raw_payload), dumps=_json_dumps),
                            None if observation.stat_type is None else str(observation.stat_type),
                            observation.season,
                            None if observation.competition is None else str(observation.competition),
                            None if observation.source_url is None else str(observation.source_url),
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


def _json_dumps(value: object) -> str:
    return json.dumps(value, default=str)


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
