from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Callable
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
    RuleFund,
    TeamFund,
    team_fund_name,
    team_fund_symbol,
)
from .repository import IndexFundRepository
from .rules import (
    EQUAL_VALUE_DRIFT,
    RULE_FUNDS,
    RULE_INDEX_KIND,
    LeagueFacts,
    RuleFundDefinition,
    Weighting,
    launch_basket,
    select_members,
    value_drift,
)

logger = logging.getLogger(__name__)

ENGINE_ERRORS = (TradingEngineClientError, TradingEngineUnavailableError)
# The review runs daily at about the same time; a little slack keeps a 7-day fund on day 7.
REVIEW_SLACK = timedelta(hours=6)


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
    definitions: tuple[RuleFundDefinition, ...] = RULE_FUNDS
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def review(self, season: int, *, dry_run: bool = False) -> IndexReviewResult:
        teams = self._review_teams(season, dry_run)
        rule_reviews, rules_too_small = self._review_rules(season, dry_run)
        return replace(
            teams, reviews=teams.reviews + rule_reviews, rules_too_small=rules_too_small
        )

    def _review_rules(
        self, season: int, dry_run: bool
    ) -> tuple[tuple[FundReview, ...], dict[str, int]]:
        """Lists each rule fund once enough players meet its rule, and rebalances listed ones
        to their rule when their review is due."""
        if not self.definitions:
            return (), {}
        league = self.repository.league_facts(season)
        funds = {fund.rule_key: fund for fund in self.repository.rule_funds()}
        prices = {player.instrument_id: player.price for player in league.players}
        now = self.clock()
        reviews: list[FundReview] = []
        too_small: dict[str, int] = {}
        for definition in self.definitions:
            fund = funds.get(definition.key)
            if fund is None:
                members = select_members(definition, league)
                if len(members) < max(1, definition.min_members):
                    too_small[definition.symbol] = len(members)
                    continue
                reviews.append(self._create_rule_fund(definition, members, prices, dry_run))
                continue
            reviews.append(self._review_rule_fund(definition, fund, league, now, dry_run))
        return tuple(reviews), too_small

    def _review_rule_fund(
        self,
        definition: RuleFundDefinition,
        fund: RuleFund,
        league: LeagueFacts,
        now: datetime,
        dry_run: bool,
    ) -> FundReview:
        due = fund.last_rebalanced_at is None or (
            now - fund.last_rebalanced_at
            >= timedelta(days=definition.review_days) - REVIEW_SLACK
        )
        if due:
            selected = set(select_members(definition, league, fund.members))
            # Too few qualify, as when a data source has stopped: keep the basket as it is.
            if len(selected) < max(1, definition.min_members):
                selected = set(fund.members)
        else:
            selected = set(fund.members)
        target = selected | fund.halted_members
        added = tuple(sorted(target - fund.members))
        removed = tuple(sorted(fund.members - target))
        review = FundReview(
            name=definition.name,
            symbol=fund.symbol,
            action=ReviewAction.UNCHANGED,
            constituent_count=len(target),
            added=added,
            removed=removed,
            instrument_id=fund.instrument_id,
        )
        reinvest = fund.cash_share >= CASH_REINVEST_SHARE
        relevel = (
            due
            and definition.weighting is Weighting.EQUAL_VALUE
            and value_drift(fund.holdings) > EQUAL_VALUE_DRIFT
        )
        if not added and not removed and not reinvest and not relevel:
            return review
        if dry_run:
            return _with(review, action=ReviewAction.WOULD_REBALANCE)
        if added or removed:
            reason = f"rule result changed: {len(added)} joined, {len(removed)} left"
        elif relevel:
            reason = "re-levelling member weights"
        else:
            reason = "reinvesting cash from buyouts"
        return self._send_rebalance(
            review,
            RebalanceIndexFundCommand(
                request_id=_rebalance_request_id(
                    fund.instrument_id, fund.members, fund.cash_per_unit, target,
                    # A re-levelling repeats with the same members, so it is told apart by day.
                    extra=now.date().isoformat() if relevel else "",
                ),
                instrument_id=fund.instrument_id,
                reason=reason,
                members=tuple(sorted(target)),
            ),
            fund.symbol,
        )

    def _create_rule_fund(
        self,
        definition: RuleFundDefinition,
        members: tuple[UUID, ...],
        prices: dict,
        dry_run: bool,
    ) -> FundReview:
        review = FundReview(
            name=definition.name,
            symbol=definition.symbol,
            action=ReviewAction.WOULD_CREATE,
            constituent_count=len(members),
            added=members,
        )
        if dry_run:
            return review
        try:
            record = self.engine.create_index_fund(
                CreateIndexFundCommand(
                    symbol=definition.symbol,
                    display_name=definition.name,
                    index_kind=RULE_INDEX_KIND,
                    club=None,
                    constituents=launch_basket(definition, members, prices),
                    rule_key=definition.key,
                    category=definition.category,
                    description=definition.description,
                    rule=definition.rule(),
                    weighting=definition.weighting.value,
                )
            )
        except ENGINE_ERRORS as error:
            logger.warning("could not list %s: %s", definition.symbol, error)
            return _with(review, action=ReviewAction.FAILED, error=str(error))
        return _with(
            review,
            action=ReviewAction.CREATED,
            symbol=record.symbol,
            instrument_id=record.instrument_id,
            unit_price=record.unit_price,
        )

    def _send_rebalance(
        self, review: FundReview, command: RebalanceIndexFundCommand, symbol: str
    ) -> FundReview:
        try:
            record = self.engine.rebalance_index_fund(command)
        except ENGINE_ERRORS as error:
            # Usually a player paused for a match; the next review tries again.
            logger.warning("could not rebalance %s: %s", symbol, error)
            return _with(review, action=ReviewAction.FAILED, error=str(error))
        return _with(review, action=ReviewAction.REBALANCED, unit_price=record.unit_price_after)

    def _review_teams(self, season: int, dry_run: bool) -> IndexReviewResult:
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
            name=fund.club,
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
        return self._send_rebalance(
            review,
            RebalanceIndexFundCommand(
                request_id=_rebalance_request_id(
                    fund.instrument_id, fund.members, fund.cash_per_unit, target
                ),
                instrument_id=fund.instrument_id,
                reason=(
                    f"squad changed: {len(added)} joined, {len(removed)} left"
                    if added or removed
                    else "reinvesting cash from buyouts"
                ),
                members=tuple(sorted(target)),
            ),
            fund.symbol,
        )

    def _create(
        self, club: str, symbol: str, instrument_ids: tuple[UUID, ...], dry_run: bool
    ) -> FundReview:
        review = FundReview(
            name=club,
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


def _rebalance_request_id(
    instrument_id: UUID,
    members: frozenset[UUID],
    cash_per_unit: str,
    target: set[UUID],
    *,
    extra: str = "",
) -> str:
    """One request per fund, starting basket, and target, so a retried review replays its
    rebalance while a later change, or cash from a new buyout, makes a new one."""
    parts = [
        ",".join(sorted(str(member) for member in members)),
        cash_per_unit,
        ",".join(sorted(str(member) for member in target)),
    ]
    if extra:
        parts.append(extra)
    state = "|".join(parts)
    return f"index-review:{instrument_id}:{sha256(state.encode()).hexdigest()[:24]}"


def _unique_symbol(symbol: str, taken: set[str]) -> str:
    """Two unknown clubs can share their first three letters; number the later one."""
    if symbol not in taken:
        return symbol
    suffix = 2
    while f"{symbol}{suffix}" in taken:
        suffix += 1
    return f"{symbol}{suffix}"
