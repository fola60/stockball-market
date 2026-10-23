from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.common.images import ImageRecord
from app.market.models import (
    FixtureRecord,
    FixtureRowRecord,
    FixtureStatus,
    MarketTradeRecord,
    MatchdayRecord,
    NewsRecord,
    NextFixtureRecord,
    PlayerBriefingRecord,
    PlayerNewsRecord,
    RoundRecord,
    SparklineRange,
)
from app.market.repository import MarketRepository

MAX_SPARKLINE_INSTRUMENTS = 60
TOP_RATED_LIMIT = 5

# (window, step) per range: 13 points over a day, 15 over a week.
_SPARKLINE_WINDOWS = {
    SparklineRange.DAY: (timedelta(hours=24), timedelta(hours=2)),
    SparklineRange.WEEK: (timedelta(days=7), timedelta(hours=12)),
}

_NEWS_LOOKBACK = timedelta(days=3)
_NEWS_CANDIDATES = 300
# A player page looks further back: one player's news is sparse.
_PLAYER_NEWS_LOOKBACK = timedelta(days=21)
_PLAYER_NEWS_CANDIDATES = 60
# Club names change only when the club-to-team map is rebuilt.
_CLUB_ALIAS_TTL = timedelta(minutes=10)

# Names headlines use for clubs beyond the canonical club and FotMob's team names.
_CLUB_NICKNAMES: dict[str, tuple[str, ...]] = {
    "Manchester Utd": ("Manchester United", "Man Utd", "Man United"),
    "Manchester City": ("Man City",),
    "Tottenham": ("Spurs",),
    "Crystal Palace": ("Palace",),
    "Aston Villa": ("Villa",),
    "Wolves": ("Wolverhampton",),
}


class TooManyInstrumentsError(ValueError):
    def __init__(self, count: int) -> None:
        super().__init__(
            f"{count} instruments requested; at most {MAX_SPARKLINE_INSTRUMENTS} are allowed"
        )


class MarketService:
    def __init__(
        self,
        repository: MarketRepository,
        *,
        lineup_lock_minutes: int = 60,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._lineup_lock = timedelta(minutes=lineup_lock_minutes)
        self._lineup_lock_minutes = lineup_lock_minutes
        self._clock = clock
        self._club_alias_cache: tuple[datetime, dict[str, tuple[str, ...]]] | None = None

    def sparklines(
        self, instrument_ids: list[UUID], price_range: SparklineRange
    ) -> dict[UUID, list[str]]:
        unique_ids = list(dict.fromkeys(instrument_ids))
        if len(unique_ids) > MAX_SPARKLINE_INSTRUMENTS:
            raise TooManyInstrumentsError(len(unique_ids))
        window, step = _SPARKLINE_WINDOWS[price_range]
        return self._repository.sparklines(unique_ids, window, step)

    def matchday(self) -> MatchdayRecord:
        now = self._clock()
        upcoming = self._repository.upcoming_round()
        next_round: RoundRecord | None = None
        if upcoming is not None:
            season: int | None = upcoming[0]
            round_number = upcoming[1]
            next_round = RoundRecord(
                season=upcoming[0],
                round=round_number,
                fixtures=[
                    self._fixture(row, now)
                    for row in self._repository.round_fixtures(upcoming[0], round_number)
                ],
            )
            previous = self._repository.latest_finished_round(upcoming[0], before=round_number)
        else:
            season = self._repository.latest_season()
            previous = (
                None if season is None else self._repository.latest_finished_round(season, before=None)
            )

        top_rated = (
            []
            if season is None or previous is None
            else self._repository.top_rated(season, previous, TOP_RATED_LIMIT)
        )
        return MatchdayRecord(
            lineup_lock_minutes=self._lineup_lock_minutes,
            next_round=next_round,
            previous_round=previous,
            top_rated=top_rated,
            league_clubs=[] if season is None else self._repository.league_clubs(season),
        )

    def recent_trades(self, limit: int, hours: int) -> list[MarketTradeRecord]:
        """The largest trades in the window, newest first."""
        trades = self._repository.recent_trades(timedelta(hours=hours), limit)
        return sorted(trades, key=lambda trade: trade.executed_at, reverse=True)

    def news(self, limit: int) -> list[NewsRecord]:
        """Recent reviewed headlines about players, at most one per story and per player.

        The social classifier's player links are not reliable enough to show on their own
        (a Formula 1 story linked to a midfielder sharing a surname), so a link counts only
        when the headline names the player and the story names the player's club.
        """
        candidates = self._repository.news_candidates(
            self._clock() - _NEWS_LOOKBACK, _NEWS_CANDIDATES
        )
        club_aliases = self._club_aliases()
        seen_documents: set[UUID] = set()
        seen_players: set[UUID] = set()
        items: list[NewsRecord] = []
        for candidate in candidates:
            if candidate.document_id in seen_documents or candidate.instrument_id in seen_players:
                continue
            if not _mentions(candidate.title, _player_names(candidate.player_name)):
                continue
            aliases = club_aliases.get(candidate.club or "", ())
            if not _mentions(f"{candidate.title} {candidate.text}", aliases):
                continue
            seen_documents.add(candidate.document_id)
            seen_players.add(candidate.instrument_id)
            items.append(
                NewsRecord(
                    document_id=candidate.document_id,
                    title=candidate.title,
                    url=candidate.url,
                    source=candidate.source,
                    published_at=candidate.published_at,
                    topic=candidate.topic,
                    player_name=candidate.player_name,
                    instrument_id=candidate.instrument_id,
                )
            )
            if len(items) == limit:
                break
        return items

    def player_briefing(self, instrument_id: UUID, news_limit: int) -> PlayerBriefingRecord:
        """What a trader should know before trading a player: when trading next pauses for a
        match, whether the player is reported injured, and the latest reviewed headlines.
        Bots read the same news, so showing it keeps people on an equal footing."""
        now = self._clock()
        fixture = self._repository.next_fixture(instrument_id)
        next_fixture = None
        if fixture is not None:
            lock_at = fixture.kickoff_at - self._lineup_lock
            next_fixture = NextFixtureRecord(
                kickoff_at=fixture.kickoff_at,
                lock_at=lock_at,
                home_team=fixture.home_team,
                away_team=fixture.away_team,
                is_home=fixture.is_home,
                locked=now >= lock_at,
            )
        return PlayerBriefingRecord(
            next_fixture=next_fixture,
            availability=self._repository.availability(instrument_id),
            news=self._player_news(instrument_id, news_limit, now),
        )

    def _player_news(self, instrument_id: UUID, limit: int, now: datetime) -> list[PlayerNewsRecord]:
        candidates = self._repository.news_candidates(
            now - _PLAYER_NEWS_LOOKBACK, _PLAYER_NEWS_CANDIDATES, instrument_id
        )
        club_aliases = self._club_aliases()
        seen: set[UUID] = set()
        items: list[PlayerNewsRecord] = []
        for candidate in candidates:
            if candidate.document_id in seen:
                continue
            # The same checks as the home page: the headline names the player and the story
            # names the club, so a namesake's story is not shown.
            if not _mentions(candidate.title, _player_names(candidate.player_name)):
                continue
            aliases = club_aliases.get(candidate.club or "", ())
            if not _mentions(f"{candidate.title} {candidate.text}", aliases):
                continue
            seen.add(candidate.document_id)
            items.append(
                PlayerNewsRecord(
                    document_id=candidate.document_id,
                    title=candidate.title,
                    url=candidate.url,
                    source=candidate.source,
                    published_at=candidate.published_at,
                    topic=candidate.topic,
                )
            )
            if len(items) == limit:
                break
        return items

    def team_badge(self, team_id: str) -> ImageRecord | None:
        return self._repository.team_badge(team_id)

    def _fixture(self, row: FixtureRowRecord, now: datetime) -> FixtureRecord:
        lock_at = row.kickoff_at - self._lineup_lock
        if row.cancelled:
            status = FixtureStatus.POSTPONED
        elif row.finished:
            status = FixtureStatus.FINISHED
        elif row.started:
            status = FixtureStatus.LIVE
        elif now >= lock_at:
            status = FixtureStatus.PAUSED
        else:
            status = FixtureStatus.UPCOMING
        return FixtureRecord(
            match_id=row.match_id,
            kickoff_at=row.kickoff_at,
            lock_at=lock_at,
            status=status,
            score=row.score if status in (FixtureStatus.FINISHED, FixtureStatus.LIVE) else None,
            home=row.home,
            away=row.away,
        )

    def _club_aliases(self) -> dict[str, tuple[str, ...]]:
        now = self._clock()
        if self._club_alias_cache is not None and now - self._club_alias_cache[0] < _CLUB_ALIAS_TTL:
            return self._club_alias_cache[1]
        aliases = {
            club: tuple(dict.fromkeys([club, *names, *_CLUB_NICKNAMES.get(club, ())]))
            for club, names in self._repository.club_names().items()
        }
        self._club_alias_cache = (now, aliases)
        return aliases


def _player_names(name: str) -> tuple[str, ...]:
    parts = name.split()
    return (name,) if len(parts) < 2 else (name, parts[-1])


def _mentions(text: str, names: Iterable[str]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE)
        for name in names
        if name
    )
