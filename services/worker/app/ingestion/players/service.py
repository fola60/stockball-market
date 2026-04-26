from __future__ import annotations

from typing import Protocol

from .models import PlayerSeedResult, PremierLeaguePlayer


class PlayerProviderClient(Protocol):
    def list_league_players(
        self,
        league: int,
        season: int,
    ) -> list[PremierLeaguePlayer]: ...


class PlayerRepository(Protocol):
    def upsert_players(self, players: list[PremierLeaguePlayer]) -> int: ...


class PlayerSeedService:
    def __init__(self, client: PlayerProviderClient, repository: PlayerRepository) -> None:
        self._client = client
        self._repository = repository

    def seed_players(self, league: int, season: int) -> PlayerSeedResult:
        players = self._deduplicate_players(self._client.list_league_players(league, season))
        upserted = self._repository.upsert_players(players)
        clubs_seen = len({player.club for player in players if player.club})
        return PlayerSeedResult(
            fetched_players=len(players),
            upserted_players=upserted,
            clubs_seen=clubs_seen,
        )

    def _deduplicate_players(self, players: list[PremierLeaguePlayer]) -> list[PremierLeaguePlayer]:
        deduped: dict[tuple[str, str], PremierLeaguePlayer] = {}
        for player in players:
            deduped[(player.provider, player.provider_player_id)] = player
        return list(deduped.values())
