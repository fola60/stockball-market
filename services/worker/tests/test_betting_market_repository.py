from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from app.ingestion.betting_markets import (
    BettingMarketObservation,
    BettingMarketParticipant,
    BettingMarketSelection,
    MarketOutcomeType,
    MarketPeriod,
    MarketScope,
    PlayerMarketType,
    PostgresBettingMarketRepository,
)


class BettingMarketRepositoryTests(unittest.TestCase):
    def test_upserts_selection_participant_and_quote_through_normalized_tables(self) -> None:
        cursor = _RecordingCursor()
        connection = _RecordingConnection(cursor)
        repository = PostgresBettingMarketRepository("postgresql://test")
        observed_at = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
        participant = BettingMarketParticipant("Bukayo Saka")
        observation = BettingMarketObservation(
            selection=BettingMarketSelection(
                provider="BET365",
                provider_event_id="12345",
                fixture_provider_id=None,
                market_scope=MarketScope.PLAYER,
                market_type=PlayerMarketType.SHOTS_ON_TARGET.value,
                period=MarketPeriod.FULL_MATCH,
                outcome_type=MarketOutcomeType.AT_LEAST,
                line=Decimal("2"),
                canonical_selection_key=(
                    "SHOTS_ON_TARGET|FULL_MATCH|AT_LEAST|2|bukayo_saka"
                ),
                provider_market_label="Shots On Target",
                provider_selection_label="Bukayo Saka AT_LEAST 2",
                participants=(participant,),
                raw_payload={"provider_player_name": "Bukayo Saka"},
            ),
            decimal_odds=Decimal("2.5"),
            implied_probability=Decimal("0.4"),
            observed_at=observed_at,
            source_url="https://www.bet365.com/#/AC/B1/C1/D8/E12345/F3/I1/",
            raw_payload={"display_odds": "6/4"},
        )

        with patch(
            "app.ingestion.betting_markets.repository.psycopg2.connect",
            return_value=connection,
        ):
            count = repository.upsert_observations([observation])

        self.assertEqual(count, 1)
        self.assertTrue(connection.committed)
        queries = [query for query, _ in cursor.executions]
        self.assertIn("INSERT INTO betting_market_selections", queries[0])
        self.assertIn("DELETE FROM betting_market_selection_players", queries[1])
        self.assertIn("INSERT INTO betting_market_selection_players", queries[2])
        self.assertIn("INSERT INTO betting_market_observations", queries[3])
        self.assertIn("count(*) OVER ()", queries[2])
        self.assertEqual(cursor.executions[2][1][2], "Bukayo Saka")

    def test_lists_recently_started_event_pages_for_live_refresh(self) -> None:
        kickoff_at = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
        cursor = _RecordingCursor(
            [
                (
                    "196564288",
                    "Bournemouth",
                    "Everton",
                    "Sat 29 Aug",
                    "15:00",
                    kickoff_at,
                    "https://www.bet365.com/#/AC/B1/C1/D8/E196564288/F3/I1/",
                )
            ]
        )
        repository = PostgresBettingMarketRepository("postgres://example")
        connection = _RecordingConnection(cursor)

        with patch(
            "app.ingestion.betting_markets.repository.psycopg2.connect",
            return_value=connection,
        ):
            fixtures = repository.list_live_event_pages(
                datetime(2026, 8, 29, 14, 30, tzinfo=UTC),
                event_window_minutes=180,
                limit=20,
            )

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].provider_event_id, "196564288")
        self.assertEqual(fixtures[0].kickoff_at, kickoff_at)
        self.assertIn("latest_event_pages", cursor.executions[0][0])


class _RecordingCursor:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.executions: list[tuple[str, object]] = []
        self.rows = rows or []

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: object) -> None:
        self.executions.append((query, params))

    def fetchone(self) -> tuple[str]:
        return ("selection-id",)

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class _RecordingConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self.cursor_instance = cursor
        self.committed = False

    def __enter__(self) -> "_RecordingConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True


if __name__ == "__main__":
    unittest.main()
