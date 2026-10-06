from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .client import FotMobError


@dataclass(frozen=True)
class PlayerRating:
    player_id: str
    name: str
    team_id: str
    team_name: str
    rating: Decimal | None
    minutes: int | None
    raw: dict


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise FotMobError("Match timestamp has no timezone")
    return result


def is_finished(match: dict) -> bool:
    status = match.get("status", {})
    return (
        status.get("finished") is True
        and not status.get("cancelled")
        and not status.get("awarded")
        and status.get("reason", {}).get("short") not in {"Postp", "Ab", "Canc"}
    )


def parse_ratings(data: dict, fixture: dict, league: int) -> list[PlayerRating]:
    general = data.get("general", {})
    if str(general.get("matchId")) != str(fixture["id"]):
        raise FotMobError("Match identity mismatch")
    if str(general.get("leagueId")) != str(league):
        raise FotMobError("Match league mismatch")
    if not is_finished(data.get("header", {})) or general.get("finished") is not True:
        raise FotMobError("Match is not finished; ratings remain pending")
    if timestamp(general["matchTimeUTCDate"]) != timestamp(fixture["status"]["utcTime"]):
        raise FotMobError("Match kickoff mismatch; rediscover fixtures before retrying")
    teams = {str(fixture[side]["id"]): fixture[side]["name"] for side in ("home", "away")}
    for side in ("home", "away"):
        if str(general[f"{side}Team"]["id"]) != str(fixture[side]["id"]):
            raise FotMobError("Match teams mismatch")
    players = data.get("content", {}).get("playerStats")
    if not isinstance(players, dict) or not players:
        raise FotMobError("Final player statistics unavailable; match remains pending")
    # A truncated player map must not checkpoint a match as complete.
    lineup = data.get("content", {}).get("lineup", {})
    for side in ("homeTeam", "awayTeam"):
        starters = lineup.get(side, {}).get("starters", [])
        if len(starters) != 11 or any(str(p["id"]) not in players for p in starters):
            raise FotMobError("Incomplete starting lineup/player statistics; match remains pending")
    ratings = []
    seen = set()
    for player in players.values():
        player_id = str(player["id"])
        team_id = str(player["teamId"])
        if team_id not in teams or player_id in seen:
            raise FotMobError("Invalid or duplicate player identity")
        seen.add(player_id)
        stats = {
            stat.get("key"): stat.get("stat", {}).get("value")
            for group in player.get("stats", [])
            for stat in group.get("stats", {}).values()
        }
        value = stats.get("rating_title")
        rating = None
        if value not in (None, "", "-"):
            try:
                rating = Decimal(str(value))
            except InvalidOperation as error:
                raise FotMobError(f"Invalid player rating: {value}") from error
            if not rating.is_finite() or not 0 <= rating <= 10:
                raise FotMobError(f"Player rating out of range: {value}")
        minutes = stats.get("minutes_played")
        if minutes is not None:
            if (
                isinstance(minutes, bool)
                or int(minutes) != float(minutes)
                or not 0 <= int(minutes) <= 150
            ):
                raise FotMobError("Invalid minutes played")
            minutes = int(minutes)
        # Unused substitutes are not appearances. Unrated appearances stay NULL.
        if rating is None and not minutes:
            continue
        ratings.append(
            PlayerRating(
                player_id, player["name"], team_id, teams[team_id], rating, minutes, player
            )
        )
    if not ratings or not any(row.rating is not None for row in ratings):
        raise FotMobError("No published ratings; match remains pending")
    return ratings
