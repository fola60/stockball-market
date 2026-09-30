from __future__ import annotations

import hashlib
import math
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Iterator, Protocol, Sequence
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.database import connection as pooled_connection

from .models import StrategyEngine

RESERVE_ACCOUNT_ID = UUID("7f63e2d0-1adc-4af1-8ad0-000000000001")
RESERVE_PORTFOLIO_ID = UUID("7f63e2d0-1adc-4af1-8ad0-000000000002")


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


@dataclass(frozen=True)
class BootstrapSnapshot:
    bots: tuple[BootstrapBot, ...]
    instruments: tuple[BootstrapInstrument, ...]
    skipped_instruments: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BootstrapOptions:
    seed: int
    min_holders_per_player: int = 3
    max_player_supply_per_bot: Decimal = Decimal("20")
    reserve_supply_percent: Decimal = Decimal("10")
    max_positions_per_bot: int = 100

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
        for allocation in self.allocations:
            if allocation.bot_id is None:
                continue
            positions[allocation.bot_id] += 1
            shares[allocation.bot_id] += allocation.quantity

        position_values = tuple(positions.values())
        share_values = tuple(shares.values())
        bot_count = len(self.selected_bot_ids)
        return {
            "min_positions_per_bot": min(position_values, default=0),
            "max_positions_per_bot": max(position_values, default=0),
            "avg_positions_per_bot": round(self.bot_positions / bot_count, 2) if bot_count else 0,
            "min_shares_per_bot": min(share_values, default=0),
            "max_shares_per_bot": max(share_values, default=0),
            "avg_shares_per_bot": round(self.bot_shares / bot_count, 2) if bot_count else 0,
        }


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

    signal_ranks = {
        "stats": _rank_signal(instruments, "stats_value"),
        "market": _rank_signal(instruments, "market_value"),
        "betting": _rank_signal(instruments, "betting_probability"),
    }
    position_counts = {bot.bot_id: 0 for bot in bots}
    allocations: list[BootstrapPositionAllocation] = []
    limits = [_allocation_limits(instrument, options) for instrument in instruments]
    required_positions = sum(required_holders for _, _, required_holders in limits)
    available_positions = len(bots) * options.max_positions_per_bot
    if required_positions > available_positions:
        raise BootstrapAllocationError(
            f"allocation requires {required_positions} bot positions but the configured fleet "
            f"can hold at most {available_positions}"
        )

    for instrument, (reserve_quantity, per_bot_cap, required_holders) in zip(
        instruments, limits, strict=True
    ):
        bot_quantity = instrument.total_supply - reserve_quantity
        eligible = [
            bot
            for bot in bots
            if position_counts[bot.bot_id] < options.max_positions_per_bot
        ]
        if len(eligible) < required_holders:
            raise BootstrapAllocationError(
                f"cannot allocate {instrument.symbol}: {required_holders} holders are required "
                f"but only {len(eligible)} bots have position capacity"
            )

        weighted = [
            (
                bot,
                _profile_weight(bot, instrument, signal_ranks, options.seed),
            )
            for bot in eligible
        ]
        holders = _balanced_weighted_holders(
            weighted, position_counts, required_holders, options.seed, instrument.instrument_id
        )
        quantities = _bounded_weighted_apportion(
            bot_quantity,
            [(bot, weight) for bot, weight in weighted if bot in holders],
            per_bot_cap,
        )
        for bot, quantity in quantities:
            allocations.append(
                BootstrapPositionAllocation(
                    instrument_id=instrument.instrument_id,
                    portfolio_id=bot.portfolio_id,
                    bot_id=bot.bot_id,
                    quantity=quantity,
                    seed_price=instrument.seed_price,
                )
            )
            position_counts[bot.bot_id] += 1
        allocations.append(
            BootstrapPositionAllocation(
                instrument_id=instrument.instrument_id,
                portfolio_id=RESERVE_PORTFOLIO_ID,
                bot_id=None,
                quantity=reserve_quantity,
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
) -> tuple[int, int, int]:
    if instrument.total_supply <= 0:
        raise BootstrapAllocationError(f"{instrument.symbol} has non-positive supply")
    reserve_quantity = int(
        (Decimal(instrument.total_supply) * options.reserve_supply_percent / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    bot_quantity = instrument.total_supply - reserve_quantity
    per_bot_cap = int(
        (
            Decimal(instrument.total_supply)
            * options.max_player_supply_per_bot
            / Decimal(100)
        ).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    )
    if bot_quantity <= 0 or per_bot_cap <= 0:
        raise BootstrapAllocationError(
            f"{instrument.symbol} leaves no allocatable bot supply under the configured limits"
        )
    required_holders = max(
        options.min_holders_per_player,
        math.ceil(bot_quantity / per_bot_cap),
    )
    return reserve_quantity, per_bot_cap, required_holders


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


def _bounded_weighted_apportion(
    total: int,
    weighted_holders: Sequence[tuple[BootstrapBot, float]],
    cap: int,
) -> tuple[tuple[BootstrapBot, int], ...]:
    if total < len(weighted_holders) or total > len(weighted_holders) * cap:
        raise BootstrapAllocationError("integer allocation is infeasible under holder and cap constraints")
    quantities = {bot.bot_id: 1 for bot, _ in weighted_holders}
    by_id = {bot.bot_id: bot for bot, _ in weighted_holders}
    weights = {bot.bot_id: max(weight, 1e-9) for bot, weight in weighted_holders}
    remaining = total - len(weighted_holders)
    while remaining:
        active = [bot_id for bot_id, quantity in quantities.items() if quantity < cap]
        weight_sum = sum(weights[bot_id] for bot_id in active)
        quotas = {bot_id: remaining * weights[bot_id] / weight_sum for bot_id in active}
        grants = {
            bot_id: min(cap - quantities[bot_id], int(math.floor(quota)))
            for bot_id, quota in quotas.items()
        }
        granted = sum(grants.values())
        if granted == 0:
            winner = max(
                active,
                key=lambda bot_id: (quotas[bot_id], str(bot_id)),
            )
            grants[winner] = 1
            granted = 1
        for bot_id, quantity in grants.items():
            quantities[bot_id] += quantity
        remaining -= granted
    return tuple(
        (by_id[bot_id], quantity)
        for bot_id, quantity in sorted(quantities.items(), key=lambda item: str(item[0]))
    )


def _unit_random(seed: int, *parts: object) -> float:
    payload = ":".join([str(seed), *(str(part) for part in parts)]).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return (value + 1) / ((1 << 64) + 1)


class PostgresSyntheticPortfolioBootstrapRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

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
                   p.cash_balance,
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
        social = [str(row["id"]) for row in rows if row["strategy_engine"] == "SOCIAL_SENTIMENT"]
        if social and not all_active:
            raise BootstrapAllocationError(
                f"social-sentiment bots are excluded from bootstrap: {', '.join(social)}"
            )
        return [
            BootstrapBot(
                bot_id=UUID(str(row["id"])),
                account_id=UUID(str(row["account_id"])),
                portfolio_id=UUID(str(row["portfolio_id"])),
                bot_key=str(row["bot_key"]),
                strategy_engine=StrategyEngine(str(row["strategy_engine"])),
                cash_balance=Decimal(str(row["cash_balance"])),
            )
            for row in rows
            if row["strategy_engine"] != "SOCIAL_SENTIMENT"
        ]

    def _load_instruments(self, cursor) -> tuple[list[BootstrapInstrument], list[tuple[str, str]]]:
        cursor.execute(
            """
            SELECT i.id, i.player_id, i.symbol,
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
                   stats.stats_value,
                   betting.betting_probability,
                   allocation.instrument_id IS NOT NULL AS bootstrapped
            FROM instruments AS i
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
                SELECT AVG(
                    COALESCE(rating::double precision / 10.0, 0.0)
                    + CASE
                        WHEN (stats ->> 'goals') ~ '^-?[0-9]+([.][0-9]+)?$'
                        THEN (stats ->> 'goals')::double precision ELSE 0.0
                      END
                    + CASE
                        WHEN (stats ->> 'assists') ~ '^-?[0-9]+([.][0-9]+)?$'
                        THEN (stats ->> 'assists')::double precision * 0.7 ELSE 0.0
                      END
                ) AS stats_value
                FROM player_stat_observations WHERE player_id = i.player_id
            ) AS stats ON true
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
        instruments: list[BootstrapInstrument] = []
        skipped: list[tuple[str, str]] = []
        for row in cursor.fetchall():
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
                    stats_value=None if row["stats_value"] is None else float(row["stats_value"]),
                    market_value=None if row["market_value"] is None else float(row["market_value"]),
                    betting_probability=(
                        None
                        if row["betting_probability"] is None
                        else float(row["betting_probability"])
                    ),
                )
            )
        return instruments, skipped

    def persist(self, plan: BootstrapAllocationPlan, options: BootstrapOptions) -> None:
        instrument_ids = sorted({item.instrument_id for item in plan.allocations}, key=str)
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM instruments WHERE id::text = ANY(%s) FOR UPDATE",
                        ([str(item) for item in instrument_ids],),
                    )
                    cursor.execute(
                        """
                        SELECT instrument_id FROM synthetic_portfolio_bootstrap_allocations
                        WHERE instrument_id::text = ANY(%s) LIMIT 1
                        """,
                        ([str(item) for item in instrument_ids],),
                    )
                    existing = cursor.fetchone()
                    if existing is not None:
                        raise BootstrapAlreadyExistsError(
                            f"bootstrap allocation already exists for instrument {existing[0]}"
                        )
                    cursor.execute(
                        """
                        SELECT instrument_id FROM positions
                        WHERE instrument_id::text = ANY(%s)
                        UNION ALL
                        SELECT instrument_id FROM orders
                        WHERE instrument_id::text = ANY(%s)
                        UNION ALL
                        SELECT instrument_id FROM trades
                        WHERE instrument_id::text = ANY(%s)
                        LIMIT 1
                        """,
                        (
                            [str(item) for item in instrument_ids],
                            [str(item) for item in instrument_ids],
                            [str(item) for item in instrument_ids],
                        ),
                    )
                    owned = cursor.fetchone()
                    if owned is not None:
                        raise BootstrapAllocationError(
                            f"instrument {owned[0]} acquired market history while bootstrap was being prepared"
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
                                    "selected_bot_ids": [str(item) for item in plan.selected_bot_ids],
                                }
                            ),
                        ),
                    )
                    batch_id = cursor.fetchone()[0]
                    for item in plan.allocations:
                        cursor.execute(
                            """
                            INSERT INTO positions (portfolio_id, instrument_id, quantity)
                            VALUES (%s, %s, %s)
                            """,
                            (str(item.portfolio_id), str(item.instrument_id), item.quantity),
                        )
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
                    cursor.execute(
                        """
                        SELECT i.symbol
                        FROM instruments AS i
                        LEFT JOIN positions AS p ON p.instrument_id = i.id
                        WHERE i.id::text = ANY(%s)
                        GROUP BY i.id
                        HAVING SUM(p.quantity) <> i.shares_outstanding
                        LIMIT 1
                        """,
                        ([str(item) for item in instrument_ids],),
                    )
                    mismatch = cursor.fetchone()
                    if mismatch is not None:
                        raise BootstrapAllocationError(
                            f"supply reconciliation failed for instrument {mismatch[0]}"
                        )
