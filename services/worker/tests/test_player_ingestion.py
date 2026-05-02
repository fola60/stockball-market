from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

import httpx

from app.ingestion.players import ExternalPlayer, FootballDataClient, PlayerSeedService
from app.jobs import IngestPlayersJobHandler, IngestPlayersJobPayload, JobType, WorkerJob


class FakePlayerRepository:
    def __init__(self) -> None:
        self.players: list[ExternalPlayer] = []

    def upsert_players(self, players: list[ExternalPlayer]) -> int:
        self.players.extend(players)
        return len(players)


class FakePlayerClient:
    def __init__(self, players: list[ExternalPlayer]) -> None:
        self.players = players
        self.calls: list[tuple[int, int]] = []

    def list_league_players(self, league: int, season: int) -> list[ExternalPlayer]:
        self.calls.append((league, season))
        return self.players


class FootballDataClientTests(unittest.TestCase):
    def test_list_competition_squad_players_fetches_team_squads(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v4/competitions/PL/teams":
                return _json_response(
                    {
                        "teams": [
                            {"id": 57, "name": "Arsenal FC"},
                            {"id": 66, "name": "Manchester United FC"},
                        ]
                    }
                )
            if request.url.path == "/v4/teams/57":
                return _json_response(
                    {
                        "id": 57,
                        "name": "Arsenal FC",
                        "squad": [
                            {
                                "id": 123,
                                "name": "Bukayo Saka",
                                "position": "Right Winger",
                                "dateOfBirth": "2001-09-05",
                                "nationality": "England",
                            }
                        ],
                    }
                )
            if request.url.path == "/v4/teams/66":
                return _json_response({"id": 66, "name": "Manchester United FC", "squad": []})
            return httpx.Response(404)

        client = FootballDataClient(
            api_token="token",
            base_url="https://api.football-data.org/v4",
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )

        players = client.list_competition_squad_players("PL")

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0].provider, "https://api.football-data.org/v4")
        self.assertEqual(players[0].provider_player_id, "123")
        self.assertEqual(players[0].display_name, "Bukayo Saka")
        self.assertEqual(players[0].club, "Arsenal FC")
        self.assertEqual(players[0].metadata["team_id"], "57")
        self.assertEqual(players[0].metadata["nationality"], "England")

    def test_rate_limit_response_is_retried_after_wait(self) -> None:
        calls = 0
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return _json_response({"teams": []})

        client = FootballDataClient(
            api_token="token",
            base_url="https://api.football-data.org/v4",
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
            sleeper=sleeps.append,
        )

        players = client.list_competition_squad_players("PL")

        self.assertEqual(players, [])
        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [2.0])


class PlayerSeedServiceTests(unittest.TestCase):
    def test_seed_players_deduplicates_and_upserts_players(self) -> None:
        player = ExternalPlayer(
            provider="FBREF",
            provider_player_id="bc7dc64d",
            display_name="Bukayo Saka",
            club="Arsenal",
            position="Attacker",
            metadata={},
        )
        repository = FakePlayerRepository()
        service = PlayerSeedService(client=FakePlayerClient([player, player]), repository=repository)

        result = service.seed_players(league=9, season=2025)

        self.assertEqual(result.fetched_players, 1)
        self.assertEqual(result.upserted_players, 1)
        self.assertEqual(result.clubs_seen, 1)
        self.assertEqual(repository.players, [player])

    def test_ingest_players_job_handler_runs_seed_service(self) -> None:
        player = ExternalPlayer(
            provider="FBREF",
            provider_player_id="bc7dc64d",
            display_name="Bukayo Saka",
            club="Arsenal",
            position="Attacker",
            metadata={},
        )
        client = FakePlayerClient([player])
        service = PlayerSeedService(client=client, repository=FakePlayerRepository())
        handler = IngestPlayersJobHandler(
            player_seed_service=service,
            clock=lambda: datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.ingest_players(IngestPlayersJobPayload(league=9, season=2025))
        )

        self.assertEqual(result.job_type, JobType.INGEST_PLAYERS)
        self.assertEqual(result.successful_items, 1)
        self.assertEqual(client.calls, [(9, 2025)])


def _json_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


if __name__ == "__main__":
    unittest.main()
