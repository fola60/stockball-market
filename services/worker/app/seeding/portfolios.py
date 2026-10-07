from __future__ import annotations

import hashlib
import math
import random
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Iterator, Mapping, Protocol, Sequence
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.clients.trading_engine import (
    InitialSupplyAllocation,
    InitialSupplyIssuer,
    IssueInitialSupplyCommand,
    TradingEngineClientError,
)
from app.database import connection as pooled_connection
from app.player_stats import load_stat_profiles, stats_value
from app.seasons import current_season
from app.synthetic_traders.models import StrategyEngine

RESERVE_ACCOUNT_ID = UUID("7f63e2d0-1adc-4af1-8ad0-000000000001")
RESERVE_PORTFOLIO_ID = UUID("7f63e2d0-1adc-4af1-8ad0-000000000002")
_MAX_APPORTION_ROUNDS = 64


class BootstrapAllocationError(ValueError):
    pass


class BootstrapAlreadyExistsError(BootstrapAllocationError):
    pass


@dataclass(frozen=True)
class BootstrapBot:
    bot_id: UUID
    account_id: UUID
    portfolio_id: UUID
    bot_key: str
    strategy_engine: StrategyEngine
    cash_balance: Decimal = Decimal("0")
    # The bot's own risk limits as fractions of equity (None when its profile sets none). The
    # seed keeps every bot inside them so it doesn't start out forced to sell.
    max_player_position_pct: float | None = None
    max_team_exposure_pct: float | None = None
    min_cash_reserve_pct: float | None = None


@dataclass(frozen=True)
class BootstrapInstrument:
    instrument_id: UUID
    player_id: UUID
    symbol: str
    seed_price: Decimal
    total_supply: int
    stats_value: float | None = None
    market_value: float | None = None
    betting_probability: float | None = None
    club: str | None = None


@dataclass(frozen=True)
class BootstrapSnapshot:
    bots: tuple[BootstrapBot, ...]
    instruments: tuple[BootstrapInstrument, ...]
    skipped_instruments: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BootstrapOptions:
    """Seed allocation limits.

    Holder counts follow value, as in a real market: the most valuable player is held by
    `top_player_holder_percent` of the bots, and every other player by that share scaled by
    (its seed price / the top seed price) ** `holder_price_exponent`, never fewer than
    `min_holders_per_player`. Each bot's number of positions follows from those targets, with
    diversified strategies holding more players than noise traders.

    Each bot is seeded with roughly `target_seed_value_per_bot` (jittered by
    `seed_value_jitter_percent`) split over its players by preference. Every position, club
    and cash balance stays within `risk_limit_headroom_percent` of the bot's own risk limits,
    so no bot starts out forced to sell; value that doesn't fit stays as cash.

    `reserve_supply_percent` is the minimum share of each player's supply kept by the reserve;
    the reserve also takes whatever the bots don't. `max_player_supply_per_bot` caps any one
    bot's share of a player's supply, and `max_positions_per_bot` caps its position count.
    """

    seed: int
    min_holders_per_player: int = 3
    max_player_supply_per_bot: Decimal = Decimal("20")
    reserve_supply_percent: Decimal = Decimal("10")
    max_positions_per_bot: int = 100
    top_player_holder_percent: Decimal = Decimal("40")
    holder_price_exponent: float = 1.0
    target_seed_value_per_bot: Decimal = Decimal("250000")
    seed_value_jitter_percent: Decimal = Decimal("25")
    risk_limit_headroom_percent: Decimal = Decimal("75")

    def validate(self) -> None:
        if not -(1 << 63) <= self.seed < (1 << 63):
            raise BootstrapAllocationError("seed must fit in a signed 64-bit integer")
        if self.min_holders_per_player <= 0:
            raise BootstrapAllocationError("min holders per player must be positive")
        if self.max_positions_per_bot <= 0:
            raise BootstrapAllocationError("max positions per bot must be positive")
        if not Decimal("0") < self.max_player_supply_per_bot <= Decimal("100"):
            raise BootstrapAllocationError("max player supply per bot must be in (0, 100]")
        if not Decimal("0") < self.reserve_supply_percent < Decimal("100"):
            raise BootstrapAllocationError("reserve supply percent must be in (0, 100)")
        if not Decimal("0") < self.top_player_holder_percent <= Decimal("100"):
            raise BootstrapAllocationError("top player holder percent must be in (0, 100]")
        if not Decimal("0") < self.risk_limit_headroom_percent <= Decimal("100"):
            raise BootstrapAllocationError("risk limit headroom percent must be in (0, 100]")
        if (
            not self.target_seed_value_per_bot.is_finite()
            or self.target_seed_value_per_bot <= 0
        ):
            raise BootstrapAllocationError("target seed value per bot must be positive")
        if not Decimal("0") <= self.seed_value_jitter_percent < Decimal("100"):
            raise BootstrapAllocationError("seed value jitter percent must be in [0, 100)")
        if not 0.0 <= self.holder_price_exponent <= 2.0:
            raise BootstrapAllocationError("holder price exponent must be in [0, 2]")


@dataclass(frozen=True)
class BootstrapPositionAllocation:
    instrument_id: UUID
    portfolio_id: UUID
    bot_id: UUID | None
    quantity: int
    seed_price: Decimal
    is_reserve: bool = False


@dataclass(frozen=True)
class BootstrapAllocationPlan:
    seed: int
    selected_bot_ids: tuple[UUID, ...]
    allocations: tuple[BootstrapPositionAllocation, ...]
    instruments_processed: int
    skipped_instruments: tuple[tuple[str, str], ...]
    bot_cash_balances: tuple[Decimal, ...] = ()

    @property
    def bot_shares(self) -> int:
        return sum(item.quantity for item in self.allocations if not item.is_reserve)

    @property
    def reserve_shares(self) -> int:
        return sum(item.quantity for item in self.allocations if item.is_reserve)

    @property
    def created_positions(self) -> int:
        return len(self.allocations)

    @property
    def bot_positions(self) -> int:
        return sum(1 for item in self.allocations if not item.is_reserve)

    @property
    def reserve_positions(self) -> int:
        return sum(1 for item in self.allocations if item.is_reserve)

    @property
    def total_bot_cash(self) -> Decimal:
        return sum(self.bot_cash_balances, Decimal("0"))

    @property
    def average_bot_cash(self) -> Decimal:
        if not self.bot_cash_balances:
            return Decimal("0")
        return self.total_bot_cash / Decimal(len(self.bot_cash_balances))

    def bot_distribution(self) -> dict[str, int | float]:
        positions = {bot_id: 0 for bot_id in self.selected_bot_ids}
        shares = {bot_id: 0 for bot_id in self.selected_bot_ids}
        values = {bot_id: Decimal("0") for bot_id in self.selected_bot_ids}
        for allocation in self.allocations:
            if allocation.bot_id is None:
                continue
            positions[allocation.bot_id] += 1
            shares[allocation.bot_id] += allocation.quantity
            values[allocation.bot_id] += allocation.quantity * allocation.seed_price

        position_values = tuple(positions.values())
        share_values = tuple(shares.values())
        seed_values = tuple(float(value) for value in values.values())
        bot_count = len(self.selected_bot_ids)
        return {
            "min_positions_per_bot": min(position_values, default=0),
            "median_positions_per_bot": _median(position_values),
            "max_positions_per_bot": max(position_values, default=0),
            "avg_positions_per_bot": round(self.bot_positions / bot_count, 2) if bot_count else 0,
            "min_shares_per_bot": min(share_values, default=0),
            "max_shares_per_bot": max(share_values, default=0),
            "avg_shares_per_bot": round(self.bot_shares / bot_count, 2) if bot_count else 0,
            "min_seed_value_per_bot": round(min(seed_values, default=0.0), 2),
            "median_seed_value_per_bot": round(_median(seed_values), 2),
            "max_seed_value_per_bot": round(max(seed_values, default=0.0), 2),
        }


    def holders_by_price_quintile(self) -> list[dict[str, float]]:
        """Average bot holders per player, cheapest fifth of players first."""
        holders: dict[UUID, int] = {}
        prices: dict[UUID, Decimal] = {}
        for allocation in self.allocations:
            prices[allocation.instrument_id] = allocation.seed_price
            if allocation.bot_id is not None:
                holders[allocation.instrument_id] = holders.get(allocation.instrument_id, 0) + 1
        ordered = sorted(prices, key=lambda instrument_id: (prices[instrument_id], str(instrument_id)))
        quintiles: list[dict[str, float]] = []
        for quintile in range(5):
            members = ordered[len(ordered) * quintile // 5 : len(ordered) * (quintile + 1) // 5]
            if not members:
                continue
            quintiles.append(
                {
                    "min_price": float(prices[members[0]]),
                    "max_price": float(prices[members[-1]]),
                    "avg_holders": round(
                        sum(holders.get(item, 0) for item in members) / len(members), 2
                    ),
                }
            )
        return quintiles


class BootstrapRepository(Protocol):
    def load_snapshot(
        self,
        *,
        bot_ids: Sequence[UUID],
        all_active_synthetic_bots: bool,
    ) -> BootstrapSnapshot: ...

    def persist(self, plan: BootstrapAllocationPlan, options: BootstrapOptions) -> None: ...


class SyntheticPortfolioBootstrapService:
    def __init__(self, repository: BootstrapRepository) -> None:
        self._repository = repository

    def bootstrap(
        self,
        *,
        bot_ids: Sequence[UUID] = (),
        all_active_synthetic_bots: bool = False,
        seed: int | None = None,
        min_holders_per_player: int = 3,
        max_player_supply_per_bot: Decimal = Decimal("20"),
        reserve_supply_percent: Decimal = Decimal("10"),
        max_positions_per_bot: int = 100,
        top_player_holder_percent: Decimal = Decimal("40"),
        holder_price_exponent: float = 1.0,
        target_seed_value_per_bot: Decimal = Decimal("250000"),
        seed_value_jitter_percent: Decimal = Decimal("25"),
        risk_limit_headroom_percent: Decimal = Decimal("75"),
        dry_run: bool = False,
    ) -> BootstrapAllocationPlan:
        if bool(bot_ids) == all_active_synthetic_bots:
            raise BootstrapAllocationError(
                "select bots with either --bot-id or --all-active-synthetic-bots"
            )
        resolved_seed = seed if seed is not None else secrets.randbits(63)
        options = BootstrapOptions(
            seed=resolved_seed,
            min_holders_per_player=min_holders_per_player,
            max_player_supply_per_bot=max_player_supply_per_bot,
            reserve_supply_percent=reserve_supply_percent,
            max_positions_per_bot=max_positions_per_bot,
            top_player_holder_percent=top_player_holder_percent,
            holder_price_exponent=holder_price_exponent,
            target_seed_value_per_bot=target_seed_value_per_bot,
            seed_value_jitter_percent=seed_value_jitter_percent,
            risk_limit_headroom_percent=risk_limit_headroom_percent,
        )
        options.validate()
        snapshot = self._repository.load_snapshot(
            bot_ids=bot_ids,
            all_active_synthetic_bots=all_active_synthetic_bots,
        )
        plan = allocate_bootstrap(snapshot, options)
        if not dry_run and plan.instruments_processed:
            self._repository.persist(plan, options)
        return plan


def allocate_bootstrap(
    snapshot: BootstrapSnapshot,
    options: BootstrapOptions,
) -> BootstrapAllocationPlan:
    options.validate()
    bots = tuple(sorted(snapshot.bots, key=lambda bot: str(bot.bot_id)))
    instruments = tuple(sorted(snapshot.instruments, key=lambda item: str(item.instrument_id)))
    if not bots:
        raise BootstrapAllocationError("no eligible synthetic traders were selected")
    if len(bots) < options.min_holders_per_player:
        raise BootstrapAllocationError(
            f"selected {len(bots)} bots but at least {options.min_holders_per_player} are required"
        )
    required_positions = len(instruments) * options.min_holders_per_player
    available_positions = len(bots) * options.max_positions_per_bot
    if required_positions > available_positions:
        raise BootstrapAllocationError(
            f"allocation requires {required_positions} bot positions but the configured fleet "
            f"can hold at most {available_positions}"
        )
    limits = [_allocation_limits(instrument, options) for instrument in instruments]

    signal_ranks = {
        "stats": _rank_signal(instruments, "stats_value"),
        "market": _rank_signal(instruments, "market_value"),
        "betting": _rank_signal(instruments, "betting_probability"),
    }
    # Each bot's preference for each player, indexed like `instruments` and reused by every stage.
    preferences = {
        bot.bot_id: [
            _profile_weight(bot, instrument, signal_ranks, options.seed)
            for instrument in instruments
        ]
        for bot in bots
    }
    holdings: dict[UUID, set[int]] = {bot.bot_id: set() for bot in bots}
    position_counts = {bot.bot_id: 0 for bot in bots}

    # Stage 1: every player gets its minimum number of holders, spread over the bots that
    # hold the fewest players so far. Players are visited in a seeded order so no player
    # is systematically left with the most-loaded bots.
    floor_order = sorted(
        range(len(instruments)),
        key=lambda index: _unit_random(options.seed, instruments[index].instrument_id, "floor"),
    )
    for index in floor_order:
        instrument = instruments[index]
        eligible = [
            (bot, preferences[bot.bot_id][index])
            for bot in bots
            if position_counts[bot.bot_id] < options.max_positions_per_bot
        ]
        if len(eligible) < options.min_holders_per_player:
            raise BootstrapAllocationError(
                f"cannot allocate {instrument.symbol}: {options.min_holders_per_player} holders "
                f"are required but only {len(eligible)} bots have position capacity"
            )
        for bot in _balanced_weighted_holders(
            eligible,
            position_counts,
            options.min_holders_per_player,
            options.seed,
            instrument.instrument_id,
        ):
            holdings[bot.bot_id].add(index)
            position_counts[bot.bot_id] += 1

    # Stage 2: more valuable players get more holders, as in a real market. Each player gets a
    # holder target set by its value, each bot a position count that adds up to those targets,
    # and bots then take turns claiming players, weighted by their own strategy preference
    # times how far the player is below target.
    budgets = {bot.bot_id: _seed_budget(bot, options) for bot in bots}
    holder_targets = _holder_targets(instruments, limits, len(bots), options)
    position_targets = _position_targets(
        bots, sum(holder_targets), len(instruments), budgets, holdings, options
    )
    holder_counts = [0] * len(instruments)
    for held in holdings.values():
        for index in held:
            holder_counts[index] += 1
    needs = [max(target - count, 0) for target, count in zip(holder_targets, holder_counts)]
    rng = random.Random(_seed_int(options.seed, "holder-fill"))
    waiting = [bot for bot in bots if len(holdings[bot.bot_id]) < position_targets[bot.bot_id]]
    while waiting:
        rng.shuffle(waiting)
        still_waiting: list[BootstrapBot] = []
        for bot in waiting:
            held = holdings[bot.bot_id]
            weights = preferences[bot.bot_id]
            best_index, best_key = -1, math.inf
            for index, need in enumerate(needs):
                if need <= 0 or index in held:
                    continue
                key = -math.log(1.0 - rng.random()) / (max(weights[index], 1e-9) * need)
                if key < best_key:
                    best_index, best_key = index, key
            if best_index < 0:
                continue
            held.add(best_index)
            needs[best_index] -= 1
            if len(held) < position_targets[bot.bot_id]:
                still_waiting.append(bot)
        waiting = still_waiting

    # Stage 3: split each bot's seed value over its players, within supply limits.
    quantities = _apportion_seed_value(
        bots, instruments, limits, holdings, preferences, budgets, options
    )

    allocations: list[BootstrapPositionAllocation] = []
    for index, instrument in enumerate(instruments):
        bot_quantity = 0
        for bot, quantity in quantities[index]:
            allocations.append(
                BootstrapPositionAllocation(
                    instrument_id=instrument.instrument_id,
                    portfolio_id=bot.portfolio_id,
                    bot_id=bot.bot_id,
                    quantity=quantity,
                    seed_price=instrument.seed_price,
                )
            )
            bot_quantity += quantity
        allocations.append(
            BootstrapPositionAllocation(
                instrument_id=instrument.instrument_id,
                portfolio_id=RESERVE_PORTFOLIO_ID,
                bot_id=None,
                quantity=instrument.total_supply - bot_quantity,
                seed_price=instrument.seed_price,
                is_reserve=True,
            )
        )

    return BootstrapAllocationPlan(
        seed=options.seed,
        selected_bot_ids=tuple(bot.bot_id for bot in bots),
        allocations=tuple(allocations),
        instruments_processed=len(instruments),
        skipped_instruments=snapshot.skipped_instruments,
        bot_cash_balances=tuple(bot.cash_balance for bot in bots),
    )


def _allocation_limits(
    instrument: BootstrapInstrument,
    options: BootstrapOptions,
) -> tuple[int, int]:
    """Return (shares bots may hold in total, shares any one bot may hold)."""
    if instrument.total_supply <= 0:
        raise BootstrapAllocationError(f"{instrument.symbol} has non-positive supply")
    if instrument.seed_price <= 0:
        raise BootstrapAllocationError(f"{instrument.symbol} has a non-positive seed price")
    min_reserve = int(
        (Decimal(instrument.total_supply) * options.reserve_supply_percent / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    bot_capacity = instrument.total_supply - min_reserve
    per_bot_cap = int(
        (
            Decimal(instrument.total_supply)
            * options.max_player_supply_per_bot
            / Decimal(100)
        ).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    )
    if bot_capacity < options.min_holders_per_player or per_bot_cap <= 0:
        raise BootstrapAllocationError(
            f"{instrument.symbol} leaves no allocatable bot supply under the configured limits"
        )
    return bot_capacity, per_bot_cap


# How many players each strategy holds relative to the fleet average: diversified strategies
# spread wider, noise traders concentrate.
_POSITION_BREADTH = {
    StrategyEngine.PORTFOLIO_REBALANCER: 1.5,
    StrategyEngine.STATS_VALUE: 1.2,
    StrategyEngine.BETTING_MARKET_VALUE: 1.0,
    StrategyEngine.MARKET_MOMENTUM: 0.9,
    StrategyEngine.NOISE: 0.8,
    StrategyEngine.SOCIAL_SENTIMENT: 0.8,
    # Short-horizon traders unwind after each match; a small book keeps that selling modest.
    StrategyEngine.EVENT_REACTION: 0.6,
}


@dataclass(frozen=True)
class _SeedBudget:
    value: float
    player_cap: float | None
    club_cap: float | None


def _holder_targets(
    instruments: Sequence[BootstrapInstrument],
    limits: Sequence[tuple[int, int]],
    bot_count: int,
    options: BootstrapOptions,
) -> list[int]:
    """Holders each player should end up with: `top_player_holder_percent` of the fleet for
    the most valuable player, scaled by (price / top price) ** holder_price_exponent for the
    rest, never below the floor, and never more than there are bots or shares to hold."""
    top_price = max(float(item.seed_price) for item in instruments)
    top_share = float(options.top_player_holder_percent) / 100.0
    targets = []
    for instrument, (bot_capacity, _) in zip(instruments, limits, strict=True):
        relative = (float(instrument.seed_price) / top_price) ** options.holder_price_exponent
        target = max(options.min_holders_per_player, round(top_share * relative * bot_count))
        targets.append(min(target, bot_count, bot_capacity))
    return targets


def _position_targets(
    bots: Sequence[BootstrapBot],
    total_slots: int,
    instrument_count: int,
    budgets: Mapping[UUID, "_SeedBudget"],
    holdings: Mapping[UUID, set[int]],
    options: BootstrapOptions,
) -> dict[UUID, int]:
    """Split the players' holder targets into per-bot position counts, weighted by strategy
    breadth with seeded jitter. A bot always gets enough positions to place its seed value
    without any one of them breaching its per-player risk limit."""
    weights = {
        bot.bot_id: _POSITION_BREADTH.get(bot.strategy_engine, 1.0)
        * (0.5 + _unit_random(options.seed, bot.bot_id, "breadth"))
        for bot in bots
    }
    weight_sum = sum(weights.values())
    exact = {bot_id: total_slots * weight / weight_sum for bot_id, weight in weights.items()}
    counts = {bot_id: int(math.floor(value)) for bot_id, value in exact.items()}
    remainder = total_slots - sum(counts.values())
    for bot_id in sorted(exact, key=lambda item: (counts[item] - exact[item], str(item)))[
        : max(remainder, 0)
    ]:
        counts[bot_id] += 1
    ceiling = min(options.max_positions_per_bot, instrument_count)
    targets: dict[UUID, int] = {}
    for bot in bots:
        budget = budgets[bot.bot_id]
        needed = 1
        if budget.player_cap is not None and budget.player_cap > 0:
            needed = math.ceil(budget.value / budget.player_cap)
        target = max(counts[bot.bot_id], needed, len(holdings[bot.bot_id]), 1)
        targets[bot.bot_id] = min(target, max(ceiling, len(holdings[bot.bot_id])))
    return targets


def _seed_budget(bot: BootstrapBot, options: BootstrapOptions) -> "_SeedBudget":
    """The bot's seed value and the most it may hold in one player or one club, all kept
    `risk_limit_headroom_percent` inside its own risk limits."""
    jitter = float(options.seed_value_jitter_percent) / 100.0
    spread = 2.0 * _unit_random(options.seed, bot.bot_id, "value") - 1.0
    value = float(options.target_seed_value_per_bot) * (1.0 + jitter * spread)
    headroom = float(options.risk_limit_headroom_percent) / 100.0
    cash = float(bot.cash_balance)
    if bot.min_cash_reserve_pct and cash > 0:
        # Keep cash / (cash + seed) at or above the reserve divided by the headroom.
        required_share = min(bot.min_cash_reserve_pct / headroom, 1.0)
        value = min(value, max(cash / required_share - cash, 0.0))
    equity = cash + value
    return _SeedBudget(
        value=value,
        player_cap=(
            None
            if bot.max_player_position_pct is None
            else bot.max_player_position_pct * headroom * equity
        ),
        club_cap=(
            None
            if bot.max_team_exposure_pct is None
            else bot.max_team_exposure_pct * headroom * equity
        ),
    )


def _seed_int(seed: int, *parts: object) -> int:
    payload = ":".join([str(seed), *(str(part) for part in parts)]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _apportion_seed_value(
    bots: Sequence[BootstrapBot],
    instruments: Sequence[BootstrapInstrument],
    limits: Sequence[tuple[int, int]],
    holdings: dict[UUID, set[int]],
    preferences: dict[UUID, list[float]],
    budgets: Mapping[UUID, "_SeedBudget"],
    options: BootstrapOptions,
) -> list[list[tuple[BootstrapBot, int]]]:
    """Water-fill each bot's seed value over its players.

    A bot's value goes to its players in proportion to its preference for them. A position
    closes when it reaches the per-bot supply cap or the bot's per-player risk limit, all of a
    bot's positions in a club close when the club reaches the bot's club limit, and a player
    closes when its bot capacity runs out; the bot's unplaced value then flows to its remaining
    open positions on the next round. Value that fits nowhere stays as cash. Returns integer
    share quantities per instrument, at least one share per holder.
    """
    prices = [float(instrument.seed_price) for instrument in instruments]
    positions: list[tuple[BootstrapBot, int, float]] = []
    position_caps: list[float] = []
    by_bot: dict[UUID, list[int]] = {}
    for bot in bots:
        player_cap = budgets[bot.bot_id].player_cap
        for index in sorted(holdings[bot.bot_id]):
            # Jitter the split so a bot's positions aren't all the same size.
            jitter = 0.5 + _unit_random(options.seed, bot.bot_id, instruments[index].instrument_id, "split")
            by_bot.setdefault(bot.bot_id, []).append(len(positions))
            positions.append((bot, index, preferences[bot.bot_id][index] * jitter))
            cap = float(limits[index][1])
            if player_cap is not None:
                cap = min(cap, player_cap / prices[index])
            position_caps.append(cap)

    shares = [0.0] * len(positions)
    is_open = [True] * len(positions)
    used = [0.0] * len(instruments)
    club_used: dict[tuple[UUID, str], float] = {}
    remaining = {bot.bot_id: budgets[bot.bot_id].value for bot in bots}
    for _ in range(_MAX_APPORTION_ROUNDS):
        additions: dict[int, float] = {}
        for bot in bots:
            if remaining[bot.bot_id] <= 0.01:
                continue
            live = [position for position in by_bot.get(bot.bot_id, ()) if is_open[position]]
            weight_sum = sum(positions[position][2] for position in live)
            if weight_sum <= 0:
                continue
            for position in live:
                index = positions[position][1]
                wanted = remaining[bot.bot_id] * positions[position][2] / weight_sum / prices[index]
                additions[position] = max(min(wanted, position_caps[position] - shares[position]), 0.0)
        if not additions:
            break

        # A bot's club limit scales down everything it is adding in that club this round.
        club_demand: dict[tuple[UUID, str], float] = {}
        for position, amount in additions.items():
            bot, index, _ = positions[position]
            club = instruments[index].club
            if club is not None and budgets[bot.bot_id].club_cap is not None:
                key = (bot.bot_id, club)
                club_demand[key] = club_demand.get(key, 0.0) + amount * prices[index]
        club_scale: dict[tuple[UUID, str], float] = {}
        for key, wanted in club_demand.items():
            club_cap = budgets[key[0]].club_cap or 0.0
            free = club_cap - club_used.get(key, 0.0)
            if wanted > 0 and wanted >= free:
                club_scale[key] = max(free, 0.0) / wanted
        for position in additions:
            bot, index, _ = positions[position]
            club = instruments[index].club
            if club is not None and (bot.bot_id, club) in club_scale:
                additions[position] *= club_scale[(bot.bot_id, club)]

        demand = [0.0] * len(instruments)
        for position, amount in additions.items():
            demand[positions[position][1]] += amount
        scale = [1.0] * len(instruments)
        full = [False] * len(instruments)
        for index, wanted in enumerate(demand):
            free = limits[index][0] - used[index]
            if wanted > 0 and wanted >= free:
                scale[index] = max(free, 0.0) / wanted
                full[index] = True

        for position, amount in additions.items():
            bot, index, _ = positions[position]
            amount *= scale[index]
            shares[position] += amount
            used[index] += amount
            remaining[bot.bot_id] -= amount * prices[index]
            club = instruments[index].club
            if club is not None:
                key = (bot.bot_id, club)
                club_used[key] = club_used.get(key, 0.0) + amount * prices[index]
            if (
                full[index]
                or shares[position] >= position_caps[position] - 1e-9
                or (club is not None and (bot.bot_id, club) in club_scale)
            ):
                is_open[position] = False

    quantities: list[list[tuple[BootstrapBot, int]]] = [[] for _ in instruments]
    for position, (bot, index, _) in enumerate(positions):
        quantities[index].append((bot, max(1, int(math.floor(shares[position] + 1e-9)))))
    for index, holders in enumerate(quantities):
        # Rounding every holder up to one share can overshoot a nearly-full player; trim the
        # largest positions back until the bots fit inside the player's capacity again.
        excess = sum(quantity for _, quantity in holders) - limits[index][0]
        while excess > 0:
            largest = max(range(len(holders)), key=lambda item: (holders[item][1], -item))
            bot, quantity = holders[largest]
            trimmed = min(excess, quantity - 1)
            holders[largest] = (bot, quantity - trimmed)
            excess -= trimmed
        holders.sort(key=lambda item: str(item[0].bot_id))
    return quantities


def _rank_signal(
    instruments: Sequence[BootstrapInstrument],
    attribute: str,
) -> dict[UUID, float]:
    known = sorted(
        (
            (float(value), instrument.instrument_id)
            for instrument in instruments
            if (value := getattr(instrument, attribute)) is not None
        ),
        key=lambda item: (item[0], str(item[1])),
    )
    if not known:
        return {instrument.instrument_id: 0.5 for instrument in instruments}
    if len(known) == 1:
        ranks = {known[0][1]: 0.5}
    else:
        ranks: dict[UUID, float] = {}
        index = 0
        while index < len(known):
            group_end = index + 1
            while group_end < len(known) and known[group_end][0] == known[index][0]:
                group_end += 1
            average_index = (index + group_end - 1) / 2
            rank = average_index / (len(known) - 1)
            for _, instrument_id in known[index:group_end]:
                ranks[instrument_id] = rank
            index = group_end
    return {instrument.instrument_id: ranks.get(instrument.instrument_id, 0.5) for instrument in instruments}


def _profile_weight(
    bot: BootstrapBot,
    instrument: BootstrapInstrument,
    ranks: dict[str, dict[UUID, float]],
    seed: int,
) -> float:
    stats = ranks["stats"][instrument.instrument_id]
    market = ranks["market"][instrument.instrument_id]
    betting = ranks["betting"][instrument.instrument_id]
    random_score = _unit_random(seed, bot.bot_id, instrument.instrument_id, "preference")
    if bot.strategy_engine is StrategyEngine.STATS_VALUE:
        return 0.05 + 0.60 * stats + 0.30 * market + 0.05 * random_score
    if bot.strategy_engine is StrategyEngine.BETTING_MARKET_VALUE:
        return 0.05 + 0.65 * betting + 0.20 * stats + 0.05 * market + 0.05 * random_score
    if bot.strategy_engine is StrategyEngine.MARKET_MOMENTUM:
        return 0.20 + 0.30 * market + 0.50 * random_score
    if bot.strategy_engine is StrategyEngine.NOISE:
        return 0.10 + 0.15 * market + 0.75 * random_score
    if bot.strategy_engine is StrategyEngine.PORTFOLIO_REBALANCER:
        return 1.0 + 0.05 * stats + 0.05 * market + 0.05 * random_score
    if bot.strategy_engine is StrategyEngine.EVENT_REACTION:
        return 0.10 + 0.35 * stats + 0.30 * betting + 0.25 * random_score
    if bot.strategy_engine is StrategyEngine.SOCIAL_SENTIMENT:
        # News follows famous players, so lean on market value; the rest is taste.
        return 0.10 + 0.35 * market + 0.55 * random_score
    raise BootstrapAllocationError(
        f"strategy {bot.strategy_engine.value} is not eligible for bootstrap allocation"
    )


def _weighted_sample_without_replacement(
    weighted: Sequence[tuple[BootstrapBot, float]],
    count: int,
    seed: int,
    instrument_id: UUID,
) -> tuple[BootstrapBot, ...]:
    ranked = sorted(
        weighted,
        key=lambda item: (
            -math.log(max(_unit_random(seed, item[0].bot_id, instrument_id, "holder"), 1e-15))
            / max(item[1], 1e-9),
            str(item[0].bot_id),
        ),
    )
    return tuple(bot for bot, _ in ranked[:count])


def _balanced_weighted_holders(
    weighted: Sequence[tuple[BootstrapBot, float]],
    position_counts: dict[UUID, int],
    count: int,
    seed: int,
    instrument_id: UUID,
) -> tuple[BootstrapBot, ...]:
    selected: list[BootstrapBot] = []
    for position_count in sorted({position_counts[bot.bot_id] for bot, _ in weighted}):
        group = [
            (bot, weight)
            for bot, weight in weighted
            if position_counts[bot.bot_id] == position_count
        ]
        needed = count - len(selected)
        if needed <= 0:
            break
        if len(group) <= needed:
            selected.extend(bot for bot, _ in group)
        else:
            selected.extend(
                _weighted_sample_without_replacement(group, needed, seed, instrument_id)
            )
    return tuple(selected)


def _risk_limit(row: Mapping[str, object], key: str, rebalancer_key: str | None = None) -> float | None:
    """A bot's effective risk limit, resolved the way the tick service resolves it: the
    `risk` section (bot overrides first), then the rebalancer's `portfolio_targets`."""
    for source in (row.get("config_overrides"), row.get("config")):
        if not isinstance(source, Mapping):
            continue
        risk = source.get("risk")
        if isinstance(risk, Mapping) and risk.get(key) is not None:
            return float(risk[key])
    for source in (row.get("config_overrides"), row.get("config")):
        if not isinstance(source, Mapping):
            continue
        targets = source.get("portfolio_targets")
        target_key = rebalancer_key or key
        if isinstance(targets, Mapping) and targets.get(target_key) is not None:
            return float(targets[target_key])
    return None


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _unit_random(seed: int, *parts: object) -> float:
    payload = ":".join([str(seed), *(str(part) for part in parts)]).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return (value + 1) / ((1 << 64) + 1)


class PostgresSyntheticPortfolioBootstrapRepository:
    def __init__(self, database_url: str, supply_issuer: InitialSupplyIssuer) -> None:
        self._database_url = database_url
        self._supply_issuer = supply_issuer

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def load_snapshot(
        self,
        *,
        bot_ids: Sequence[UUID],
        all_active_synthetic_bots: bool,
    ) -> BootstrapSnapshot:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                bots = self._load_bots(cursor, bot_ids, all_active_synthetic_bots)
                instruments, skipped = self._load_instruments(cursor)
        return BootstrapSnapshot(tuple(bots), tuple(instruments), tuple(skipped))

    def _load_bots(self, cursor, bot_ids: Sequence[UUID], all_active: bool) -> list[BootstrapBot]:
        where = "b.status = 'ACTIVE'" if all_active else "b.id::text = ANY(%(bot_ids)s)"
        cursor.execute(
            f"""
            SELECT b.id, b.account_id, p.id AS portfolio_id, b.bot_key, c.strategy_engine,
                   p.cash_balance, c.config, b.config_overrides,
                   b.status, a.account_type
            FROM synthetic_trader_bots AS b
            JOIN synthetic_trader_bot_configs AS c ON c.id = b.config_id
            JOIN accounts AS a ON a.id = b.account_id
            JOIN portfolios AS p ON p.account_id = a.id
            WHERE {where}
            ORDER BY b.id
            """,
            {"bot_ids": [str(bot_id) for bot_id in bot_ids]},
        )
        rows = cursor.fetchall()
        if not all_active and len(rows) != len(set(bot_ids)):
            found = {UUID(str(row["id"])) for row in rows}
            missing = sorted(str(bot_id) for bot_id in set(bot_ids) - found)
            raise BootstrapAllocationError(f"synthetic bots not found: {', '.join(missing)}")
        invalid = [
            str(row["id"])
            for row in rows
            if row["status"] != "ACTIVE" or row["account_type"] != "SYNTHETIC_TRADER"
        ]
        if invalid:
            raise BootstrapAllocationError(f"bots are not active synthetic traders: {', '.join(invalid)}")
        return [
            BootstrapBot(
                bot_id=UUID(str(row["id"])),
                account_id=UUID(str(row["account_id"])),
                portfolio_id=UUID(str(row["portfolio_id"])),
                bot_key=str(row["bot_key"]),
                strategy_engine=StrategyEngine(str(row["strategy_engine"])),
                cash_balance=Decimal(str(row["cash_balance"])),
                max_player_position_pct=_risk_limit(row, "max_player_position_pct"),
                max_team_exposure_pct=_risk_limit(row, "max_team_exposure_pct"),
                min_cash_reserve_pct=_risk_limit(row, "min_cash_reserve_pct", "min_cash_pct"),
            )
            for row in rows
        ]

    def _load_instruments(self, cursor) -> tuple[list[BootstrapInstrument], list[tuple[str, str]]]:
        cursor.execute(
            """
            SELECT i.id, i.player_id, i.symbol, player.club,
                   COALESCE(seed_price.new_price, i.current_price) AS seed_price,
                   i.shares_outstanding,
                   COALESCE(owned.quantity, 0) AS owned_quantity,
                   COALESCE(owned.position_count, 0) AS position_count,
                   EXISTS (
                       SELECT 1 FROM orders WHERE instrument_id = i.id
                   ) OR EXISTS (
                       SELECT 1 FROM trades WHERE instrument_id = i.id
                   ) AS has_market_activity,
                   mv.value AS market_value,
                   betting.betting_probability,
                   allocation.instrument_id IS NOT NULL AS bootstrapped
            FROM instruments AS i
            LEFT JOIN players AS player ON player.id = i.player_id
            LEFT JOIN (
                SELECT instrument_id, SUM(quantity) AS quantity, COUNT(*) AS position_count
                FROM positions GROUP BY instrument_id
            ) AS owned ON owned.instrument_id = i.id
            LEFT JOIN LATERAL (
                SELECT value FROM player_market_value_observations
                WHERE player_id = i.player_id AND currency = 'EUR'
                ORDER BY observed_at DESC, id DESC LIMIT 1
            ) AS mv ON true
            LEFT JOIN LATERAL (
                SELECT new_price FROM price_snapshots
                WHERE instrument_id = i.id AND reason = 'SEED'
                ORDER BY captured_at ASC, id ASC LIMIT 1
            ) AS seed_price ON true
            LEFT JOIN LATERAL (
                SELECT AVG(latest.implied_probability)::double precision AS betting_probability
                FROM (
                    SELECT DISTINCT ON (s.id) o.implied_probability
                    FROM betting_market_selection_players AS bp
                    JOIN betting_market_selections AS s ON s.id = bp.selection_id
                    JOIN betting_market_observations AS o ON o.selection_id = s.id
                    WHERE bp.player_id = i.player_id AND bp.participant_role = 'PRIMARY'
                    ORDER BY s.id, o.observed_at DESC, o.id DESC
                ) AS latest
            ) AS betting ON true
            LEFT JOIN LATERAL (
                SELECT instrument_id FROM synthetic_portfolio_bootstrap_allocations
                WHERE instrument_id = i.id LIMIT 1
            ) AS allocation ON true
            WHERE i.instrument_type = 'PLAYER_SHARE' AND i.trading_status = 'ACTIVE'
            ORDER BY i.id
            """
        )
        rows = cursor.fetchall()
        now = datetime.now(UTC)
        values = {
            player_id: stats_value(profile)
            for player_id, profile in load_stat_profiles(
                cursor, current_season(now), now.date()
            ).items()
        }
        instruments: list[BootstrapInstrument] = []
        skipped: list[tuple[str, str]] = []
        for row in rows:
            symbol = str(row["symbol"])
            if row["bootstrapped"]:
                raise BootstrapAlreadyExistsError(
                    f"bootstrap allocation already exists for instrument {symbol}"
                )
            if row["has_market_activity"]:
                raise BootstrapAllocationError(
                    f"{symbol} already has order or trade history"
                )
            supply = Decimal(str(row["shares_outstanding"]))
            owned = Decimal(str(row["owned_quantity"]))
            if owned == supply and supply > 0:
                skipped.append((symbol, "supply already fully owned"))
                continue
            if owned != 0:
                raise BootstrapAllocationError(
                    f"{symbol} has partially owned supply ({owned} of {supply})"
                )
            if int(row["position_count"]) != 0:
                raise BootstrapAllocationError(
                    f"{symbol} already has position history"
                )
            if supply != supply.to_integral_value():
                skipped.append((symbol, "non-integer seed supply"))
                continue
            instruments.append(
                BootstrapInstrument(
                    instrument_id=UUID(str(row["id"])),
                    player_id=UUID(str(row["player_id"])),
                    symbol=symbol,
                    seed_price=Decimal(str(row["seed_price"])),
                    total_supply=int(supply),
                    stats_value=values.get(str(row["player_id"])),
                    market_value=None if row["market_value"] is None else float(row["market_value"]),
                    betting_probability=(
                        None
                        if row["betting_probability"] is None
                        else float(row["betting_probability"])
                    ),
                    club=row["club"],
                )
            )
        return instruments, skipped

    def persist(self, plan: BootstrapAllocationPlan, options: BootstrapOptions) -> None:
        by_instrument: dict[UUID, list[BootstrapPositionAllocation]] = {}
        for item in plan.allocations:
            by_instrument.setdefault(item.instrument_id, []).append(item)
        instrument_ids = [str(item) for item in by_instrument]

        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT instrument_id FROM synthetic_portfolio_bootstrap_allocations
                        WHERE instrument_id::text = ANY(%s) LIMIT 1
                        """,
                        (instrument_ids,),
                    )
                    existing = cursor.fetchone()
                    if existing is not None:
                        raise BootstrapAlreadyExistsError(
                            f"bootstrap allocation already exists for instrument {existing[0]}"
                        )
                    cursor.execute(
                        """
                        INSERT INTO synthetic_portfolio_bootstrap_batches (seed, parameters)
                        VALUES (%s, %s) RETURNING id
                        """,
                        (
                            plan.seed,
                            Json(
                                {
                                    "min_holders_per_player": options.min_holders_per_player,
                                    "max_player_supply_per_bot": str(options.max_player_supply_per_bot),
                                    "reserve_supply_percent": str(options.reserve_supply_percent),
                                    "max_positions_per_bot": options.max_positions_per_bot,
                                    "top_player_holder_percent": str(options.top_player_holder_percent),
                                    "risk_limit_headroom_percent": str(options.risk_limit_headroom_percent),
                                    "target_seed_value_per_bot": str(options.target_seed_value_per_bot),
                                    "seed_value_jitter_percent": str(options.seed_value_jitter_percent),
                                    "holder_price_exponent": options.holder_price_exponent,
                                    "selected_bot_ids": [str(item) for item in plan.selected_bot_ids],
                                }
                            ),
                        ),
                    )
                    batch_id = cursor.fetchone()[0]

            # Positions are owned by the trading engine, which checks each instrument is still
            # pre-market and that its supply is issued in full. Each instrument is one engine
            # call; the audit rows are recorded as soon as its supply has been issued.
            for instrument_id, allocations in by_instrument.items():
                self._issue_supply(batch_id, instrument_id, allocations)
                with connection:
                    with connection.cursor() as cursor:
                        for item in allocations:
                            cursor.execute(
                                """
                                INSERT INTO synthetic_portfolio_bootstrap_allocations (
                                    batch_id, instrument_id, portfolio_id, bot_id,
                                    quantity, seed_price, is_reserve
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    batch_id,
                                    str(item.instrument_id),
                                    str(item.portfolio_id),
                                    None if item.bot_id is None else str(item.bot_id),
                                    item.quantity,
                                    item.seed_price,
                                    item.is_reserve,
                                ),
                            )

    def _issue_supply(
        self,
        batch_id: object,
        instrument_id: UUID,
        allocations: Sequence[BootstrapPositionAllocation],
    ) -> None:
        command = IssueInitialSupplyCommand(
            request_id=f"initial-supply:{batch_id}:{instrument_id}",
            allocations=tuple(
                InitialSupplyAllocation(
                    instrument_id=item.instrument_id,
                    portfolio_id=item.portfolio_id,
                    quantity=str(item.quantity),
                )
                for item in allocations
            ),
        )
        try:
            self._supply_issuer.issue_initial_supply(command)
        except TradingEngineClientError as exc:
            code = exc.body.get("code")
            if code == "instrument_has_market_activity":
                raise BootstrapAllocationError(
                    f"instrument {instrument_id} acquired market history while bootstrap was being prepared"
                ) from exc
            if code == "supply_mismatch":
                raise BootstrapAllocationError(
                    f"supply reconciliation failed for instrument {instrument_id}"
                ) from exc
            raise
