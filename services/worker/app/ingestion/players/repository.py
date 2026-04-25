from __future__ import annotations

import psycopg2
from psycopg2.extras import Json

from .models import PremierLeaguePlayer


class PostgresPlayerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_players(self, players: list[PremierLeaguePlayer]) -> int:
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
            connection.commit()

        return len(players)
