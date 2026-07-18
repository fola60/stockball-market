from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.ingestion.social.twitter import TwitterIngestionCursor, TwitterRateLimit
from app.ingestion.social.twitter.repository import PostgresTwitterInjuryRepository


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


class PostgresTwitterInjuryRepositoryTests(unittest.TestCase):
    def test_page_checkpoint_keeps_since_id_and_pending_newest_id_separate(self) -> None:
        connection = _RecordingConnection()
        repository = PostgresTwitterInjuryRepository("postgresql://test")
        cursor = TwitterIngestionCursor(
            query_key="injuries-v1",
            query="injury -is:retweet",
            since_id="100",
            next_token="opaque-next-token",
            pending_newest_id="200",
            rate_limit=TwitterRateLimit(450, 449, NOW),
        )

        with patch(
            "app.ingestion.social.twitter.repository.psycopg2.connect",
            return_value=connection,
        ):
            repository.checkpoint_cursor(cursor, NOW)

        params = connection.cursor_instance.executions[0][1]
        self.assertEqual(params[2], "100")
        self.assertEqual(params[3], "opaque-next-token")
        self.assertEqual(params[4], "200")

    def test_completion_clears_pagination_and_promotes_newest_to_since_id(self) -> None:
        connection = _RecordingConnection()
        repository = PostgresTwitterInjuryRepository("postgresql://test")

        with patch(
            "app.ingestion.social.twitter.repository.psycopg2.connect",
            return_value=connection,
        ):
            repository.complete_cursor(
                "injuries-v1",
                "injury -is:retweet",
                "200",
                TwitterRateLimit(450, 448, NOW),
                NOW,
            )

        params = connection.cursor_instance.executions[0][1]
        self.assertEqual(params[2], "200")
        self.assertIsNone(params[3])
        self.assertIsNone(params[4])


class _RecordingCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executions.append((query, params))


class _RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = _RecordingCursor()

    def __enter__(self) -> "_RecordingConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self, **kwargs: object) -> _RecordingCursor:
        return self.cursor_instance

    def close(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
