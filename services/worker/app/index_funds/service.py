from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from hashlib import sha256
from uuid import UUID

from app.clients import (
    CreateIndexFundCommand,
    IndexFundClient,
    RebalanceIndexFundCommand,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)

from .models import (
    CASH_REINVEST_SHARE,
    MIN_TEAM_PLAYERS,
    TEAM_INDEX_KIND,
    TEAM_SHARES_PER_UNIT,
    FundReview,
    IndexReviewResult,
    ReviewAction,
    TeamFund,
    team_fund_name,
    team_fund_symbol,
)
from .repository import IndexFundRepository

logger = logging.getLogger(__name__)

ENGINE_ERRORS = (TradingEngineClientError, TradingEngineUnavailableError)


@dataclass
class IndexReviewService:
    """Keeps every index fund in line with its rule.

    The team rule picks each league club's current-season players who can trade. A club
    without a fund gets one; a fund whose rule result has changed is rebalanced to it. The
    engine trades custody from the old basket to the new one without changing a unit's value.

    Players halted for leaving the league stay in their fund until their buyout: a rebalance
    cannot sell them, and the buyout turns them into cash that the next rebalance spends.
    """

    repository: IndexFundRepository
    engine: IndexFundClient

    def review(self, season: int, *, dry_run: bool = False) -> IndexReviewResult:
        rosters = {
            roster.club.casefold(): roster for roster in self.repository.team_rosters(season)
        }
        funds = {fund.club.casefold(): fund for fund in self.repository.team_funds()}
        taken_symbols = {fund.symbol for fund in funds.values()}
        reviews: list[FundReview] = []
        too_small: dict[str, int] = {}

        for key in sorted(rosters):
            roster = rosters[key]
            fund = funds.get(key)
            if fund is not None:
                reviews.append(self._rebalance(fund, set(roster.instrument_ids), dry_run))
                continue
            if len(roster.instrument_ids) < MIN_TEAM_PLAYERS:
                too_small[roster.club] = len(roster.instrument_ids)
                continue
            symbol = _unique_symbol(team_fund_symbol(roster.club), taken_symbols)
            taken_symbols.add(symbol)
            reviews.append(self._create(roster.club, symbol, roster.instrument_ids, dry_run))

        return IndexReviewResult(
            season=season,
            dry_run=dry_run,
            reviews=tuple(reviews),
            too_small=too_small,
            without_roster=tuple(
                sorted(fund.club for key, fund in funds.items() if key not in rosters)
            ),
        )

    def _rebalance(self, fund: TeamFund, rule_members: set[UUID], dry_run: bool) -> FundReview:
        target = rule_members | fund.halted_members
        added = tuple(sorted(target - fund.members))
        removed = tuple(sorted(fund.members - target))
        review = FundReview(
            club=fund.club,
            symbol=fund.symbol,
            action=ReviewAction.UNCHANGED,
            constituent_count=len(target),
            added=added,
            removed=removed,
            instrument_id=fund.instrument_id,
        )
        reinvest = fund.cash_share >= CASH_REINVEST_SHARE
        if not added and not removed and not reinvest:
            return review
        if dry_run:
            return _with(review, action=ReviewAction.WOULD_REBALANCE)
        try:
            record = self.engine.rebalance_index_fund(
                RebalanceIndexFundCommand(
                    request_id=_rebalance_request_id(fund, target),
                    instrument_id=fund.instrument_id,
                    reason=(
                        f"squad changed: {len(added)} joined, {len(removed)} left"
                        if added or removed
                        else "reinvesting cash from buyouts"
                    ),
                    members=tuple(sorted(target)),
                )
            )
        except ENGINE_ERRORS as error:
            # Usually a player paused for a match; the next review tries again.
            logger.warning("could not rebalance %s: %s", fund.symbol, error)
            return _with(review, action=ReviewAction.FAILED, error=str(error))
        return _with(review, action=ReviewAction.REBALANCED, unit_price=record.unit_price_after)

    def _create(
        self, club: str, symbol: str, instrument_ids: tuple[UUID, ...], dry_run: bool
    ) -> FundReview:
        review = FundReview(
            club=club,
            symbol=symbol,
            action=ReviewAction.WOULD_CREATE,
            constituent_count=len(instrument_ids),
            added=tuple(sorted(instrument_ids)),
        )
        if dry_run:
            return review
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
        except ENGINE_ERRORS as error:
            logger.warning("could not list the %s index fund: %s", club, error)
            return _with(review, action=ReviewAction.FAILED, error=str(error))
        return _with(
            review,
            action=ReviewAction.CREATED,
            symbol=record.symbol,
            instrument_id=record.instrument_id,
            unit_price=record.unit_price,
        )


def _with(review: FundReview, **changes) -> FundReview:
    return replace(review, **changes)


def _rebalance_request_id(fund: TeamFund, target: set[UUID]) -> str:
    """One request per fund, starting basket, and target, so a retried review replays its
    rebalance while a later change, or cash from a new buyout, makes a new one."""
    state = "|".join(
        [
            ",".join(sorted(str(member) for member in fund.members)),
            fund.cash_per_unit,
            ",".join(sorted(str(member) for member in target)),
        ]
    )
    return f"index-review:{fund.instrument_id}:{sha256(state.encode()).hexdigest()[:24]}"


def _unique_symbol(symbol: str, taken: set[str]) -> str:
    """Two unknown clubs can share their first three letters; number the later one."""
    if symbol not in taken:
        return symbol
    suffix = 2
    while f"{symbol}{suffix}" in taken:
        suffix += 1
    return f"{symbol}{suffix}"
