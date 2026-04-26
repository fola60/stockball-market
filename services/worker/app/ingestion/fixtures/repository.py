from __future__ import annotations

import psycopg2
from psycopg2.extras import Json

from .models import ApiFootballFixture


class PostgresFixtureRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_fixtures(self, fixtures: list[ApiFootballFixture]) -> int:
        if not fixtures:
            return 0

        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                for fixture in fixtures:
                    cursor.execute(
                        """
                        INSERT INTO fixtures (
                            provider,
                            provider_fixture_id,
                            league_provider_id,
                            season,
                            kickoff_at,
                            home_team_provider_id,
                            home_team_name,
                            away_team_provider_id,
                            away_team_name,
                            status_short,
                            status_long,
                            elapsed,
                            raw_payload,
                            updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
                        )
                        ON CONFLICT (provider, provider_fixture_id) DO UPDATE
                        SET
                            league_provider_id = EXCLUDED.league_provider_id,
                            season = EXCLUDED.season,
                            kickoff_at = EXCLUDED.kickoff_at,
                            home_team_provider_id = EXCLUDED.home_team_provider_id,
                            home_team_name = EXCLUDED.home_team_name,
                            away_team_provider_id = EXCLUDED.away_team_provider_id,
                            away_team_name = EXCLUDED.away_team_name,
                            status_short = EXCLUDED.status_short,
                            status_long = EXCLUDED.status_long,
                            elapsed = EXCLUDED.elapsed,
                            raw_payload = EXCLUDED.raw_payload,
                            updated_at = now()
                        """,
                        (
                            fixture.provider,
                            fixture.provider_fixture_id,
                            fixture.league_provider_id,
                            fixture.season,
                            fixture.kickoff_at,
                            fixture.home_team_provider_id,
                            fixture.home_team_name,
                            fixture.away_team_provider_id,
                            fixture.away_team_name,
                            fixture.status_short,
                            fixture.status_long,
                            fixture.elapsed,
                            Json(dict(fixture.raw_payload)),
                        ),
                    )
            connection.commit()

        return len(fixtures)
