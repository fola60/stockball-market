from __future__ import annotations

import psycopg2
from psycopg2.extras import Json

from .models import ExternalPlayer


class PostgresPlayerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_players(self, players: list[ExternalPlayer]) -> int:
        if not players:
            return 0

        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                for player in players:
                    cursor.execute(
                        """
                        INSERT INTO players (
                            provider,
                            provider_player_id,
                            display_name,
                            club,
                            position,
                            metadata,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, now()
                        )
                        ON CONFLICT (provider, provider_player_id) DO UPDATE
                        SET
                            display_name = EXCLUDED.display_name,
                            club = EXCLUDED.club,
                            position = EXCLUDED.position,
                            metadata = players.metadata || EXCLUDED.metadata,
                            updated_at = now()
                        RETURNING id
                        """,
                        (
                            player.provider,
                            player.provider_player_id,
                            player.display_name,
                            player.club,
                            player.position,
                            Json(dict(player.metadata)),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        _upsert_provider_ref(cursor, str(row[0]), player)
            connection.commit()

        return len(players)


def _upsert_provider_ref(cursor: object, player_id: str, player: ExternalPlayer) -> None:
    provider_url = player.metadata.get("provider_url")
    cursor.execute(
        """
        INSERT INTO player_provider_refs (
            player_id,
            provider,
            provider_player_id,
            provider_url,
            confidence,
            is_primary,
            raw_identity,
            last_seen_at
        ) VALUES (
            %s, %s, %s, %s, %s, true, %s, now()
        )
        ON CONFLICT (provider, provider_player_id) DO UPDATE
        SET
            player_id = EXCLUDED.player_id,
            provider_url = EXCLUDED.provider_url,
            confidence = EXCLUDED.confidence,
            is_primary = EXCLUDED.is_primary,
            raw_identity = EXCLUDED.raw_identity,
            last_seen_at = now()
        """,
        (
            player_id,
            player.provider,
            player.provider_player_id,
            None if provider_url is None else str(provider_url),
            player.metadata.get("provider_confidence", 1.0),
            Json(dict(player.metadata)),
        ),
    )
