from __future__ import annotations

import logging
from dataclasses import dataclass

from app.clients import (
    CreateIndexFundCommand,
    IndexFundCreator,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)

from .models import (
    MIN_TEAM_PLAYERS,
    TEAM_INDEX_KIND,
    TEAM_SHARES_PER_UNIT,
    TeamIndexFundOutcome,
    TeamIndexFundsResult,
    team_fund_name,
    team_fund_symbol,
)
from .repository import TeamIndexFundRepository

logger = logging.getLogger(__name__)


@dataclass
class TeamIndexFundService:
    repository: TeamIndexFundRepository
    engine: IndexFundCreator

    def create_team_funds(self, season: int, *, dry_run: bool = False) -> TeamIndexFundsResult:
        """Lists a fund for every league club without one, over its current squad.

        A fund's basket is fixed when it is listed, so clubs that already have a fund are left
        alone even if their squad has changed since.
        """
        existing = {
            club.casefold(): symbol
            for club, symbol in self.repository.existing_team_funds().items()
        }
        taken_symbols = set(existing.values())
        outcomes: list[TeamIndexFundOutcome] = []
        already_listed: dict[str, str] = {}
        too_small: dict[str, int] = {}

        for roster in sorted(self.repository.team_rosters(season), key=lambda r: r.club):
            if roster.club.casefold() in existing:
                already_listed[roster.club] = existing[roster.club.casefold()]
                continue
            if len(roster.instrument_ids) < MIN_TEAM_PLAYERS:
                too_small[roster.club] = len(roster.instrument_ids)
                continue
            symbol = _unique_symbol(team_fund_symbol(roster.club), taken_symbols)
            taken_symbols.add(symbol)
            if dry_run:
                outcomes.append(
                    TeamIndexFundOutcome(roster.club, symbol, len(roster.instrument_ids))
                )
                continue
            outcomes.append(self._create(roster.club, symbol, roster.instrument_ids))

        return TeamIndexFundsResult(
            season=season,
            dry_run=dry_run,
            outcomes=tuple(outcomes),
            existing=already_listed,
            too_small=too_small,
        )

    def _create(self, club, symbol, instrument_ids) -> TeamIndexFundOutcome:
        try:
            record = self.engine.create_index_fund(
                CreateIndexFundCommand(
                    symbol=symbol,
                    display_name=team_fund_name(club),
                    index_kind=TEAM_INDEX_KIND,
                    club=club,
                    constituents=tuple(
                        (instrument_id, TEAM_SHARES_PER_UNIT) for instrument_id in instrument_ids
                    ),
                )
            )
        except (TradingEngineClientError, TradingEngineUnavailableError) as error:
            logger.warning("could not list the %s index fund: %s", club, error)
            return TeamIndexFundOutcome(club, symbol, len(instrument_ids), error=str(error))
        return TeamIndexFundOutcome(
            club,
            record.symbol,
            record.constituent_count,
            created=record.created,
            instrument_id=record.instrument_id,
            unit_price=record.unit_price,
        )


def _unique_symbol(symbol: str, taken: set[str]) -> str:
    """Two unknown clubs can share their first three letters; number the later one."""
    if symbol not in taken:
        return symbol
    suffix = 2
    while f"{symbol}{suffix}" in taken:
        suffix += 1
    return f"{symbol}{suffix}"
