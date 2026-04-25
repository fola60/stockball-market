from __future__ import annotations

from typing import Protocol

from .client import DEFAULT_COMPETITION_CODE
from .models import PlayerSeedResult, PremierLeaguePlayer


class PlayerProviderClient(Protocol):
    def list_competition_squad_players(
        self,
        competition_code: str = DEFAULT_COMPETITION_CODE,
    ) -> list[PremierLeaguePlayer]: ...


class PlayerRepository(Protocol):
    def upsert_players(self, players: list[PremierLeaguePlayer]) -> int: ...


class PlayerSeedService:
    def __init__(self, client: PlayerProviderClient, repository: PlayerRepository) -> None:
        self._client = client
        self._repository = repository

    def seed_players(self, competition_code: str = DEFAULT_COMPETITION_CODE) -> PlayerSeedResult:
        players = self._deduplicate_players(
            self._client.list_competition_squad_players(competition_code)
        )
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
