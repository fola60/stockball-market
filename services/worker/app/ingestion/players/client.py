from __future__ import annotations

import time
from typing import Any, Mapping

import httpx

from .models import PremierLeaguePlayer


DEFAULT_COMPETITION_CODE = "PL"
DEFAULT_REQUEST_INTERVAL_SECONDS = 7.0
DEFAULT_RATE_LIMIT_RETRY_SECONDS = 60.0


class FootballDataClient:
    def __init__(
        self,
        api_token: str,
        base_url: str = "https://api.football-data.org/v4",
        timeout_seconds: float = 10.0,
        request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
        rate_limit_retry_seconds: float = DEFAULT_RATE_LIMIT_RETRY_SECONDS,
        transport: httpx.BaseTransport | None = None,
        sleeper: Any = time.sleep,
        clock: Any = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._request_interval_seconds = request_interval_seconds
        self._rate_limit_retry_seconds = rate_limit_retry_seconds
        self._sleeper = sleeper
        self._clock = clock
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"X-Auth-Token": api_token},
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def provider(self) -> str:
        return self._base_url

    def list_competition_squad_players(
        self,
        competition_code: str = DEFAULT_COMPETITION_CODE,
    ) -> list[PremierLeaguePlayer]:
        teams_payload = self._get_json(f"/competitions/{competition_code}/teams")
        teams = teams_payload.get("teams", [])
        if not isinstance(teams, list):
            raise ValueError("football-data teams response must include a teams list")

        players: list[PremierLeaguePlayer] = []
        for team in teams:
            if not isinstance(team, Mapping):
                continue
            team_id = team.get("id")
            if team_id is None:
                continue
            players.extend(self._list_team_squad_players(str(team_id), team, competition_code))
        return players

    def _list_team_squad_players(
        self,
        team_id: str,
        team_summary: Mapping[str, Any],
        competition_code: str,
    ) -> list[PremierLeaguePlayer]:
        team_payload = self._get_json(f"/teams/{team_id}")
        squad = team_payload.get("squad", [])
        if not isinstance(squad, list):
            raise ValueError("football-data team response must include a squad list")

        club_name = str(team_payload.get("name") or team_summary.get("name") or "")
        players: list[PremierLeaguePlayer] = []
        for squad_member in squad:
            if not isinstance(squad_member, Mapping):
                continue
            player_id = squad_member.get("id")
            display_name = squad_member.get("name")
            if player_id is None or not display_name:
                continue
            players.append(
                PremierLeaguePlayer(
                    provider=self.provider,
                    provider_player_id=str(player_id),
                    display_name=str(display_name),
                    club=club_name,
                    position=_optional_str(squad_member.get("position")),
                    metadata={
                        "competition_code": competition_code,
                        "team_id": team_id,
                        "team_name": club_name,
                        "date_of_birth": _optional_str(squad_member.get("dateOfBirth")),
                        "nationality": _optional_str(squad_member.get("nationality")),
                        "football_data_raw": dict(squad_member),
                    },
                )
            )
        return players

    def _get_json(self, path: str) -> dict[str, Any]:
        self._throttle()
        response = self._client.get(path)
        if response.status_code == 429:
            retry_after = _retry_after_seconds(
                response.headers.get("Retry-After"),
                self._rate_limit_retry_seconds,
            )
            self._sleeper(retry_after)
            self._last_request_at = None
            self._throttle()
            response = self._client.get(path)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("football-data response must be a JSON object")
        return payload

    def _throttle(self) -> None:
        if self._request_interval_seconds <= 0:
            self._last_request_at = self._clock()
            return

        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            sleep_for = self._request_interval_seconds - elapsed
            if sleep_for > 0:
                self._sleeper(sleep_for)
                now = self._clock()
        self._last_request_at = now


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _retry_after_seconds(raw_value: str | None, default: float) -> float:
    if raw_value is None:
        return default
    try:
        return max(float(raw_value), 0.0)
    except ValueError:
        return default
