from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import httpx

from app.ingestion.fixtures.models import ApiFootballFixture
from app.ingestion.players.models import PremierLeaguePlayer
from app.ingestion.stats.models import ApiFootballPlayerStat


DEFAULT_API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_RATE_LIMIT_RETRY_SECONDS = 60.0


class ApiFootballClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_API_FOOTBALL_BASE_URL,
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
            headers={"x-apisports-key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def provider(self) -> str:
        return self._base_url

    def list_fixtures(
        self,
        league: int,
        season: int,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ApiFootballFixture]:
        params: dict[str, str | int] = {"league": league, "season": season}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if to_date is not None:
            params["to"] = to_date.isoformat()

        payload = self._get_json("/fixtures", params)
        return [
            _fixture_from_payload(self.provider, fixture_payload, league, season)
            for fixture_payload in _response_list(payload)
        ]

    def list_league_players(self, league: int, season: int) -> list[PremierLeaguePlayer]:
        players: list[PremierLeaguePlayer] = []
        page = 1
        while True:
            payload = self._get_json(
                "/players",
                {"league": league, "season": season, "page": page},
            )
            players.extend(
                _player_from_payload(self.provider, player_payload, league, season)
                for player_payload in _response_list(payload)
                if isinstance(player_payload, Mapping)
            )
            paging = _mapping(payload.get("paging"))
            current_page = int(paging.get("current") or page)
            total_pages = int(paging.get("total") or current_page)
            if current_page >= total_pages:
                break
            page = current_page + 1
        return players

    def list_fixture_player_stats(self, fixture_id: int) -> list[ApiFootballPlayerStat]:
        payload = self._get_json("/fixtures/players", {"fixture": fixture_id})
        observations: list[ApiFootballPlayerStat] = []
        for team_payload in _response_list(payload):
            if not isinstance(team_payload, Mapping):
                continue
            team = team_payload.get("team", {})
            if not isinstance(team, Mapping):
                team = {}
            team_provider_id = _optional_str(team.get("id"))
            team_name = _optional_str(team.get("name"))
            players = team_payload.get("players", [])
            if not isinstance(players, list):
                continue
            for player_payload in players:
                if not isinstance(player_payload, Mapping):
                    continue
                observation = _player_stat_from_payload(
                    self.provider,
                    str(fixture_id),
                    team_provider_id,
                    team_name,
                    player_payload,
                )
                if observation is not None:
                    observations.append(observation)
        return observations

    def _get_json(self, path: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        self._throttle()
        response = self._client.get(path, params=params)
        if response.status_code == 429:
            retry_after = _retry_after_seconds(
                response.headers.get("Retry-After"),
                self._rate_limit_retry_seconds,
            )
            self._sleeper(retry_after)
            self._last_request_at = None
            self._throttle()
            response = self._client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("API-Football response must be a JSON object")
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


def _fixture_from_payload(
    provider: str,
    payload: Mapping[str, Any],
    default_league: int,
    default_season: int,
) -> ApiFootballFixture:
    fixture = _mapping(payload.get("fixture"))
    league = _mapping(payload.get("league"))
    teams = _mapping(payload.get("teams"))
    home_team = _mapping(teams.get("home"))
    away_team = _mapping(teams.get("away"))
    status = _mapping(fixture.get("status"))

    return ApiFootballFixture(
        provider=provider,
        provider_fixture_id=str(fixture["id"]),
        league_provider_id=str(league.get("id") or default_league),
        season=int(league.get("season") or default_season),
        kickoff_at=_parse_datetime(str(fixture["date"])),
        home_team_provider_id=str(home_team["id"]),
        home_team_name=str(home_team["name"]),
        away_team_provider_id=str(away_team["id"]),
        away_team_name=str(away_team["name"]),
        status_short=_optional_str(status.get("short")),
        status_long=_optional_str(status.get("long")),
        elapsed=None if status.get("elapsed") is None else int(status["elapsed"]),
        raw_payload=dict(payload),
    )


def _player_from_payload(
    provider: str,
    payload: Mapping[str, Any],
    league: int,
    season: int,
) -> PremierLeaguePlayer:
    player = _mapping(payload.get("player"))
    statistics = payload.get("statistics", [])
    stat_payload = statistics[0] if isinstance(statistics, list) and statistics else {}
    if not isinstance(stat_payload, Mapping):
        stat_payload = {}
    team = _mapping(stat_payload.get("team"))
    games = _mapping(stat_payload.get("games"))

    return PremierLeaguePlayer(
        provider=provider,
        provider_player_id=str(player["id"]),
        display_name=str(player["name"]),
        club=str(team.get("name") or ""),
        position=_optional_str(games.get("position")),
        metadata={
            "league_id": str(league),
            "season": season,
            "team_id": _optional_str(team.get("id")),
            "team_name": _optional_str(team.get("name")),
            "age": player.get("age"),
            "date_of_birth": _optional_str(_mapping(player.get("birth")).get("date")),
            "nationality": _optional_str(player.get("nationality")),
            "height": _optional_str(player.get("height")),
            "weight": _optional_str(player.get("weight")),
            "photo": _optional_str(player.get("photo")),
            "injured": player.get("injured"),
            "api_football_raw": dict(payload),
        },
    )


def _player_stat_from_payload(
    provider: str,
    provider_fixture_id: str,
    team_provider_id: str | None,
    team_name: str | None,
    payload: Mapping[str, Any],
) -> ApiFootballPlayerStat | None:
    player = _mapping(payload.get("player"))
    player_id = player.get("id")
    player_name = player.get("name")
    if player_id is None or not player_name:
        return None

    statistics = payload.get("statistics", [])
    stat_payload = statistics[0] if isinstance(statistics, list) and statistics else {}
    if not isinstance(stat_payload, Mapping):
        stat_payload = {}

    games = _mapping(stat_payload.get("games"))
    rating = _optional_decimal(games.get("rating"))
    return ApiFootballPlayerStat(
        provider=provider,
        provider_fixture_id=provider_fixture_id,
        provider_player_id=str(player_id),
        team_provider_id=team_provider_id,
        team_name=team_name,
        display_name=str(player_name),
        rating=rating,
        stats=dict(stat_payload),
        raw_payload=dict(payload),
    )


def _response_list(payload: Mapping[str, Any]) -> list[Any]:
    response = payload.get("response", [])
    if not isinstance(response, list):
        raise ValueError("API-Football response must include a response list")
    return response


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _parse_datetime(raw_value: str) -> datetime:
    return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _retry_after_seconds(raw_value: str | None, default: float) -> float:
    if raw_value is None:
        return default
    try:
        return max(float(raw_value), 0.0)
    except ValueError:
        return default

