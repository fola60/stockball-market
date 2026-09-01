from __future__ import annotations

import psycopg2
from psycopg2.extras import Json

from .models import BettingMarketObservation


class PostgresBettingMarketRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def upsert_observations(self, observations: list[BettingMarketObservation]) -> int:
        if not observations:
            return 0
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                for observation in observations:
                    cursor.execute(
                        """
                        INSERT INTO betting_market_observations (
                            fixture_id, provider, provider_event_id, fixture_provider_id,
                            market_key, selection_key, decimal_odds, implied_probability,
                            observed_at, source_url, raw_payload
                        ) VALUES (
                            (SELECT id FROM fixtures WHERE provider_fixture_id = %s LIMIT 1),
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (provider, provider_event_id, market_key, selection_key, observed_at)
                        DO UPDATE SET
                            fixture_id = EXCLUDED.fixture_id,
                            fixture_provider_id = EXCLUDED.fixture_provider_id,
                            decimal_odds = EXCLUDED.decimal_odds,
                            implied_probability = EXCLUDED.implied_probability,
                            source_url = EXCLUDED.source_url,
                            raw_payload = EXCLUDED.raw_payload,
                            updated_at = now()
                        """,
                        (
                            observation.fixture_provider_id,
                            observation.provider,
                            observation.provider_event_id,
                            observation.fixture_provider_id,
                            observation.market_key,
                            observation.selection_key,
                            observation.decimal_odds,
                            observation.implied_probability,
                            observation.observed_at,
                            observation.source_url,
                            Json(dict(observation.raw_payload)),
                        ),
                    )
            connection.commit()
        return len(observations)
