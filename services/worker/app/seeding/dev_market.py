from __future__ import annotations

import hashlib
import math
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterator, Mapping, Protocol, Sequence
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from app.clients import (
    HttpTradingEngineClient,
    PreMarketPricer,
    SetPreMarketPriceCommand,
    TradingEngineClientError,
)
from app.database import connection as pooled_connection
from app.league_roster.models import RosterSyncResult
from app.player_stats import load_stat_profiles, stats_value
from app.seasons import CURRENT_SEASON, current_season, resolve_season
from app.synthetic_traders.models import (
    SpawnSyntheticTraderBatchResult,
    SpawnSyntheticTraderCommand,
)
from app.topups import PostgresTopupRepository, TopupCadence, TopupOutcomeStatus, TopupService

from .portfolios import SyntheticPortfolioBootstrapService

MIN_PRICE = Decimal("1.0000")
MAX_PRICE = Decimal("250.0000")


class DevMarketBootstrapError(ValueError):
    pass


@dataclass(frozen=True)
class ActivityProfileSpec:
    config_key: str
    allocation_weight: float
    decision_yield: float
    tick_cadence_minutes: int
    cooldown_minutes: int
    trade_probability: float
    max_orders_per_tick: int


DEFAULT_ACTIVITY_PROFILES = (
    ActivityProfileSpec("NOISE_RETAIL_BUYER", 0.18, 0.46, 10, 15, 0.55, 1),
    ActivityProfileSpec("NOISE_RETAIL_SELLER", 0.12, 0.38, 10, 15, 0.55, 1),
    ActivityProfileSpec("MARKET_MOMENTUM_TRADER", 0.11, 0.30, 10, 15, 0.60, 2),
    ActivityProfileSpec("STATS_VALUE_CONSERVATIVE", 0.14, 0.34, 15, 20, 0.55, 1),
    ActivityProfileSpec("STATS_VALUE_AGGRESSIVE", 0.13, 0.42, 10, 15, 0.65, 2),
    ActivityProfileSpec("SOCIAL_HYPE_CHASER", 0.09, 0.32, 10, 15, 0.60, 1),
    ActivityProfileSpec("SOCIAL_CONTRARIAN", 0.07, 0.30, 15, 20, 0.55, 1),
    ActivityProfileSpec("PORTFOLIO_REBALANCER", 0.07, 0.35, 20, 30, 0.65, 2),
    ActivityProfileSpec("BETTING_MARKET_CONSERVATIVE", 0.04, 0.28, 10, 15, 0.55, 1),
    ActivityProfileSpec("BETTING_MARKET_AGGRESSIVE", 0.05, 0.40, 5, 10, 0.65, 2),
)


@dataclass(frozen=True)
class InstrumentSignal:
    instrument_id: UUID
    symbol: str
    position: str | None
    current_price: Decimal
    market_value: float | None
    stats_value: float | None
    social_value: float | None
    recent_trade_count: int
    has_activity: bool
    has_positions: bool
    already_valued: bool


@dataclass(frozen=True)
class FleetProfileState:
    spec: ActivityProfileSpec
    base_config: Mapping[str, Any]
    existing_count: int


@dataclass(frozen=True)
class StartupSnapshot:
    player_count: int
    instruments: tuple[InstrumentSignal, ...]
    profiles: tuple[FleetProfileState, ...]
    has_portfolio_bootstrap: bool = False
    unfunded_bot_count: int = 0

    @property
    def projected_instrument_count(self) -> int:
        return max(self.player_count, len(self.instruments))


@dataclass(frozen=True)
class FleetPlanningOptions:
    target_trades_per_hour_per_instrument: float
    max_bots: int | None = 5000
    popularity_headroom: float = 0.25

    def validate(self) -> None:
        if self.target_trades_per_hour_per_instrument <= 0:
            raise DevMarketBootstrapError("target trades per hour per instrument must be positive")
        if self.max_bots is not None and self.max_bots <= 0:
            raise DevMarketBootstrapError("max bots must be positive")
        if not 0 <= self.popularity_headroom <= 2:
            raise DevMarketBootstrapError("popularity headroom must be between 0 and 2")


@dataclass(frozen=True)
class ValuationOptions:
    market_value_weight: float = 0.45
    stats_weight: float = 0.45
    social_weight: float = 0.10
    minimum_price: Decimal = MIN_PRICE
    maximum_price: Decimal = MAX_PRICE

    def validate(self) -> None:
        weights = (self.market_value_weight, self.stats_weight, self.social_weight)
        if any(weight < 0 for weight in weights) or not math.isclose(sum(weights), 1.0):
            raise DevMarketBootstrapError("valuation weights must be non-negative and sum to 1")
        if self.social_weight >= self.market_value_weight or self.social_weight >= self.stats_weight:
            raise DevMarketBootstrapError(
                "social weight must be lower than market-value and stats weights"
            )
        if (
            not self.minimum_price.is_finite()
            or not self.maximum_price.is_finite()
            or self.minimum_price <= 0
            or self.maximum_price <= self.minimum_price
        ):
            raise DevMarketBootstrapError("valuation price bounds must be positive and ordered")


@dataclass(frozen=True)
class FleetProfilePlan:
    config_key: str
    existing_count: int
    target_count: int
    create_count: int
    expected_trades_per_bot_hour: float
    expected_ticks_per_hour: float
    config_overrides: Mapping[str, Any]

    @property
    def projected_trades_per_hour(self) -> float:
        return self.target_count * self.expected_trades_per_bot_hour


@dataclass(frozen=True)
class FleetPlan:
    instrument_count: int
    target_trades_per_hour_per_instrument: float
    required_trades_per_hour: float
    projected_trades_per_hour: float
    projected_ticks_per_hour: float
    projected_min_instrument_trades_per_hour: float
    projected_max_instrument_trades_per_hour: float
    profiles: tuple[FleetProfilePlan, ...]

    @property
    def calculated_bot_count(self) -> int:
        return sum(item.target_count for item in self.profiles)

    @property
    def create_count(self) -> int:
        return sum(item.create_count for item in self.profiles)


@dataclass(frozen=True)
class InstrumentValuation:
    instrument_id: UUID
    symbol: str
    old_price: Decimal
    new_price: Decimal
    anchor_price: Decimal
    market_rank: float
    stats_rank: float
    social_rank: float


@dataclass(frozen=True)
class FundingResult:
    planned: int = 0
    applied: int = 0
    reused: int = 0
    failed: int = 0
    applied_cash: Decimal = Decimal("0")


@dataclass(frozen=True)
class PortfolioResult:
    initialized: bool = False
    instruments: int = 0
    positions: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class DevMarketBootstrapOptions:
    fleet: FleetPlanningOptions
    valuation: ValuationOptions = ValuationOptions()
    seed: int = 20260915
    funding_amount: Decimal = Decimal("100000.0000")
    min_holders_per_instrument: int = 5
    max_positions_per_bot: int = 500
    commit: bool = False
    # Players outside this season's roster are halted before the market is sized and seeded.
    season: int = CURRENT_SEASON

    @property
    def dry_run(self) -> bool:
        return not self.commit

    def validate(self) -> None:
        self.fleet.validate()
        self.valuation.validate()
        if not self.funding_amount.is_finite() or self.funding_amount <= 0:
            raise DevMarketBootstrapError("funding amount must be positive")
        if not -(1 << 63) <= self.seed < (1 << 63):
            raise DevMarketBootstrapError("random seed must fit in a signed 64-bit integer")
        if self.min_holders_per_instrument <= 0 or self.max_positions_per_bot <= 0:
            raise DevMarketBootstrapError("portfolio allocation limits must be positive")


@dataclass(frozen=True)
class DevMarketBootstrapReport:
    dry_run: bool
    seed: int
    fleet: FleetPlan
    valuations_planned: int
    valuations_applied: int
    instruments_created: int
    instruments_reused: int
    bots_created: int
    bots_reused: int
    funding: FundingResult
    portfolio: PortfolioResult
    valuation_weights: Mapping[str, float]
    roster_halted: int = 0
    roster_season: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": "dry-run" if self.dry_run else "committed",
            "seed": self.seed,
            "accounts": {
                "created": self.bots_created,
                "reused": self.bots_reused,
            },
            "instruments": {
                "active_or_projected": self.fleet.instrument_count,
                "created": self.instruments_created,
                "reused": self.instruments_reused,
                "valuations_planned": self.valuations_planned,
                "valuations_applied": self.valuations_applied,
            },
            "valuation_weights": dict(self.valuation_weights),
            "fleet": {
                "target_trades_per_hour_per_instrument": (
                    self.fleet.target_trades_per_hour_per_instrument
                ),
                "required_trades_per_hour": round(self.fleet.required_trades_per_hour, 3),
                "projected_trades_per_hour": round(self.fleet.projected_trades_per_hour, 3),
                "projected_ticks_per_hour": round(self.fleet.projected_ticks_per_hour, 3),
                "projected_min_instrument_trades_per_hour": round(
                    self.fleet.projected_min_instrument_trades_per_hour, 3
                ),
                "projected_max_instrument_trades_per_hour": round(
                    self.fleet.projected_max_instrument_trades_per_hour, 3
                ),
                "calculated_bot_count": self.fleet.calculated_bot_count,
                "created": self.bots_created,
                "reused": self.bots_reused,
                "profiles": [
                    {
                        "config_key": item.config_key,
                        "existing": item.existing_count,
                        "target": item.target_count,
                        "create": item.create_count,
                        "expected_trades_per_bot_hour": round(
                            item.expected_trades_per_bot_hour, 4
                        ),
                    }
                    for item in self.fleet.profiles
                ],
            },
            "funding": {
                "planned": self.funding.planned,
                "applied": self.funding.applied,
                "reused": self.funding.reused,
                "failed": self.funding.failed,
                "applied_cash": str(self.funding.applied_cash),
            },
            "portfolio": {
                "initialized": self.portfolio.initialized,
                "instruments": self.portfolio.instruments,
                "positions": self.portfolio.positions,
                "skipped": self.portfolio.skipped,
            },
            "roster": {"season": self.roster_season, "halted_not_in_league": self.roster_halted},
        }


class StartupRepository(Protocol):
    def load_snapshot(self) -> StartupSnapshot: ...

    def apply_valuations(
        self,
        valuations: Sequence[InstrumentValuation],
        options: ValuationOptions,
    ) -> int: ...

    def apply_activity_overrides(self, profiles: Sequence[FleetProfilePlan]) -> int: ...


class InstrumentSeeder(Protocol):
    def seed(self) -> tuple[int, int]: ...


class FleetSpawner(Protocol):
    def spawn(
        self,
        command: SpawnSyntheticTraderCommand,
    ) -> SpawnSyntheticTraderBatchResult: ...


class FleetFundService(Protocol):
    def fund(self, amount: Decimal) -> FundingResult: ...


class RosterReconciler(Protocol):
    def reconcile(self, season: int) -> RosterSyncResult: ...


class PortfolioBootstrapper(Protocol):
    def initialize(
        self,
        *,
        seed: int,
        min_holders: int,
        max_positions_per_bot: int,
    ) -> PortfolioResult: ...


@dataclass(frozen=True)
class DevMarketBootstrapService:
    repository: StartupRepository
    instrument_seeder: InstrumentSeeder
    spawner: FleetSpawner
    funder: FleetFundService
    portfolio_bootstrapper: PortfolioBootstrapper
    roster: RosterReconciler | None = None

    def run(self, options: DevMarketBootstrapOptions) -> DevMarketBootstrapReport:
        options.validate()
        instruments_created = 0
        instruments_reused = 0
        season = resolve_season(options.season)
        roster_halted = 0
        if options.commit:
            instruments_created, instruments_reused = self.instrument_seeder.seed()
            if self.roster is not None:
                roster_halted = self.roster.reconcile(season).halted

        snapshot = self.repository.load_snapshot()
        if snapshot.projected_instrument_count <= 0:
            raise DevMarketBootstrapError(
                "no players or active player-share instruments are available to bootstrap"
            )
        valuations = build_valuation_plan(snapshot.instruments, options.valuation)
        valuations_applied = (
            self.repository.apply_valuations(valuations, options.valuation)
            if options.commit
            else 0
        )
        fleet = plan_fleet(snapshot, options.fleet)

        bots_created = 0
        if options.commit:
            for profile in fleet.profiles:
                if profile.create_count <= 0:
                    continue
                result = self.spawner.spawn(
                    SpawnSyntheticTraderCommand(
                        config_key=profile.config_key,
                        count=profile.create_count,
                        random_seed=_profile_seed(options.seed, profile.config_key),
                        config_overrides=profile.config_overrides,
                    )
                )
                bots_created += int(result.spawned_count)
            self.repository.apply_activity_overrides(fleet.profiles)

        funding = (
            self.funder.fund(options.funding_amount)
            if options.commit
            else FundingResult(planned=snapshot.unfunded_bot_count + fleet.create_count)
        )
        portfolio = PortfolioResult()
        if options.commit:
            refreshed = self.repository.load_snapshot()
            if not refreshed.has_portfolio_bootstrap:
                portfolio = self.portfolio_bootstrapper.initialize(
                    seed=options.seed,
                    min_holders=options.min_holders_per_instrument,
                    max_positions_per_bot=max(
                        options.max_positions_per_bot,
                        refreshed.projected_instrument_count,
                    ),
                )

        return DevMarketBootstrapReport(
            dry_run=options.dry_run,
            seed=options.seed,
            fleet=fleet,
            valuations_planned=len(valuations),
            valuations_applied=valuations_applied,
            instruments_created=instruments_created,
            instruments_reused=(
                instruments_reused if options.commit else len(snapshot.instruments)
            ),
            bots_created=bots_created,
            bots_reused=sum(item.existing_count for item in fleet.profiles),
            funding=funding,
            portfolio=portfolio,
            valuation_weights={
                "market_value": options.valuation.market_value_weight,
                "player_stats": options.valuation.stats_weight,
                "social_sentiment": options.valuation.social_weight,
            },
            roster_halted=roster_halted,
            roster_season=season,
        )


def plan_fleet(snapshot: StartupSnapshot, options: FleetPlanningOptions) -> FleetPlan:
    options.validate()
    instrument_count = snapshot.projected_instrument_count
    if instrument_count <= 0:
        raise DevMarketBootstrapError("instrument count must be positive")
    if not snapshot.profiles:
        raise DevMarketBootstrapError("no enabled synthetic trader profiles are available")

    required = (
        options.target_trades_per_hour_per_instrument
        * instrument_count
        * (1.0 + options.popularity_headroom)
    )
    counts = {profile.spec.config_key: profile.existing_count for profile in snapshot.profiles}
    rates: dict[str, float] = {}
    ticks: dict[str, float] = {}
    overrides: dict[str, Mapping[str, Any]] = {}
    for profile in snapshot.profiles:
        override = _activity_overrides(profile.spec, instrument_count)
        effective = _deep_merge(profile.base_config, override)
        rates[profile.spec.config_key] = _expected_trades_per_hour(
            profile.spec, effective
        )
        ticks[profile.spec.config_key] = 60.0 / float(
            _nested_number(effective, "execution", "tick_cadence_minutes", default=60)
        )
        overrides[profile.spec.config_key] = override

    for profile in snapshot.profiles:
        if options.max_bots is not None and sum(counts.values()) >= options.max_bots:
            break
        counts[profile.spec.config_key] = max(counts[profile.spec.config_key], 1)

    def projected() -> float:
        return sum(counts[key] * rates[key] for key in counts)

    while projected() + 1e-9 < required:
        if options.max_bots is not None and sum(counts.values()) >= options.max_bots:
            raise DevMarketBootstrapError(
                f"target requires more than --max-bots={options.max_bots}; "
                f"projected {projected():.2f} of {required:.2f} trades/hour"
            )
        candidate = max(
            snapshot.profiles,
            key=lambda profile: (
                profile.spec.allocation_weight / (counts[profile.spec.config_key] + 1),
                rates[profile.spec.config_key],
                profile.spec.config_key,
            ),
        )
        counts[candidate.spec.config_key] += 1

    profiles = tuple(
        FleetProfilePlan(
            config_key=profile.spec.config_key,
            existing_count=profile.existing_count,
            target_count=counts[profile.spec.config_key],
            create_count=max(counts[profile.spec.config_key] - profile.existing_count, 0),
            expected_trades_per_bot_hour=rates[profile.spec.config_key],
            expected_ticks_per_hour=ticks[profile.spec.config_key],
            config_overrides=overrides[profile.spec.config_key],
        )
        for profile in snapshot.profiles
    )
    projected_total = sum(item.projected_trades_per_hour for item in profiles)
    min_projection, max_projection = _instrument_activity_range(
        snapshot,
        projected_total,
        options.target_trades_per_hour_per_instrument,
    )
    return FleetPlan(
        instrument_count=instrument_count,
        target_trades_per_hour_per_instrument=(
            options.target_trades_per_hour_per_instrument
        ),
        required_trades_per_hour=required,
        projected_trades_per_hour=projected_total,
        projected_ticks_per_hour=sum(
            item.target_count * item.expected_ticks_per_hour for item in profiles
        ),
        projected_min_instrument_trades_per_hour=min_projection,
        projected_max_instrument_trades_per_hour=max_projection,
        profiles=profiles,
    )


def build_valuation_plan(
    instruments: Sequence[InstrumentSignal],
    options: ValuationOptions,
) -> tuple[InstrumentValuation, ...]:
    options.validate()
    unsafe = [item.symbol for item in instruments if item.current_price <= 0 and item.has_activity]
    if unsafe:
        raise DevMarketBootstrapError(
            "cannot repair non-positive prices after market activity: " + ", ".join(unsafe[:10])
        )
    eligible = tuple(
        item
        for item in instruments
        if not item.has_activity and not item.has_positions and not item.already_valued
    )
    market_ranks = _rank_values(eligible, "market_value")
    stats_ranks = _rank_values(eligible, "stats_value")
    social_ranks = _rank_values(eligible, "social_value")
    plans: list[InstrumentValuation] = []
    for item in eligible:
        anchor = _anchor_price(item)
        market_rank = market_ranks[item.instrument_id]
        stats_rank = stats_ranks[item.instrument_id]
        social_rank = social_ranks[item.instrument_id]
        blended_rank = (
            options.market_value_weight * market_rank
            + options.stats_weight * stats_rank
            + options.social_weight * social_rank
        )
        multiplier = Decimal(str(0.75 + 0.5 * blended_rank))
        price = (anchor * multiplier).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        price = max(options.minimum_price, min(options.maximum_price, price))
        plans.append(
            InstrumentValuation(
                instrument_id=item.instrument_id,
                symbol=item.symbol,
                old_price=item.current_price,
                new_price=price,
                anchor_price=anchor,
                market_rank=market_rank,
                stats_rank=stats_rank,
                social_rank=social_rank,
            )
        )
    return tuple(plans)


def _expected_trades_per_hour(
    spec: ActivityProfileSpec,
    config: Mapping[str, Any],
) -> float:
    cadence = _nested_number(config, "execution", "tick_cadence_minutes", default=60)
    cooldown = _nested_number(config, "execution", "cooldown_minutes", default=0)
    probability = _nested_number(config, "execution", "trade_probability", default=0)
    orders = _nested_number(config, "execution", "max_orders_per_tick", default=1)
    daily_cap = _nested_number(config, "risk", "max_daily_trades", default=1)
    raw = (60.0 / cadence) * probability * spec.decision_yield * orders
    cooldown_cap = math.inf if cooldown <= 0 else 60.0 / cooldown
    return max(0.0, min(raw, cooldown_cap, daily_cap / 24.0))


def _activity_overrides(
    spec: ActivityProfileSpec,
    instrument_count: int,
) -> Mapping[str, Any]:
    overrides: dict[str, Any] = {
        "universe": {"max_candidates": max(instrument_count, 150)},
        "risk": {"max_daily_trades": 72, "max_daily_turnover_pct": 0.90},
        "execution": {
            "tick_cadence_minutes": spec.tick_cadence_minutes,
            "cooldown_minutes": spec.cooldown_minutes,
            "decision_jitter_minutes": min(2, spec.tick_cadence_minutes - 1),
            "trade_probability": spec.trade_probability,
            "max_orders_per_tick": spec.max_orders_per_tick,
        },
    }
    if spec.config_key in {"NOISE_RETAIL_BUYER", "NOISE_RETAIL_SELLER"}:
        overrides["randomness"] = {
            "activity_floor_minutes": 60,
            "activity_floor_weight": 0.65,
        }
    return overrides


def _instrument_activity_range(
    snapshot: StartupSnapshot,
    projected_total: float,
    floor: float,
) -> tuple[float, float]:
    count = snapshot.projected_instrument_count
    if count <= 0:
        return 0.0, 0.0
    remaining = max(projected_total - floor * count, 0.0)
    popularity = _popularity_scores(snapshot.instruments)
    popularity.extend([0.5] * (count - len(popularity)))
    weights = [0.25 + value for value in popularity]
    weight_total = sum(weights)
    projections = [floor + remaining * weight / weight_total for weight in weights]
    return min(projections), max(projections)


def _popularity_scores(instruments: Sequence[InstrumentSignal]) -> list[float]:
    if not instruments:
        return []
    market = _rank_values(instruments, "market_value")
    stats = _rank_values(instruments, "stats_value")
    social = _rank_values(instruments, "social_value")
    trades = _rank_values(instruments, "recent_trade_count")
    return [
        0.35 * market[item.instrument_id]
        + 0.30 * stats[item.instrument_id]
        + 0.10 * social[item.instrument_id]
        + 0.25 * trades[item.instrument_id]
        for item in instruments
    ]


def _rank_values(
    items: Sequence[InstrumentSignal],
    attribute: str,
) -> dict[UUID, float]:
    known = sorted(
        (
            (float(value), item.instrument_id)
            for item in items
            if (value := getattr(item, attribute)) is not None
        ),
        key=lambda pair: (pair[0], str(pair[1])),
    )
    ranks: dict[UUID, float] = {}
    if len(known) == 1:
        ranks[known[0][1]] = 0.5
    elif known:
        index = 0
        while index < len(known):
            end = index + 1
            while end < len(known) and known[end][0] == known[index][0]:
                end += 1
            rank = ((index + end - 1) / 2) / (len(known) - 1)
            for _, instrument_id in known[index:end]:
                ranks[instrument_id] = rank
            index = end
    return {item.instrument_id: ranks.get(item.instrument_id, 0.5) for item in items}


def _anchor_price(item: InstrumentSignal) -> Decimal:
    if item.market_value is not None and item.market_value > 0:
        return max(MIN_PRICE, min(MAX_PRICE, Decimal(str(item.market_value)) / Decimal("1000000")))
    position = (item.position or "").casefold()
    if "forward" in position or "wing" in position or "striker" in position or position == "fw":
        return Decimal("12.5000")
    if "mid" in position:
        return Decimal("10.0000")
    if "back" in position or "def" in position:
        return Decimal("7.5000")
    return Decimal("5.0000")


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = value
    return merged


def _nested_number(
    config: Mapping[str, Any],
    section: str,
    field: str,
    *,
    default: float,
) -> float:
    values = config.get(section)
    if not isinstance(values, Mapping):
        return default
    value = values.get(field, default)
    return float(value) if isinstance(value, int | float) else default


def _profile_seed(seed: int, config_key: str) -> int:
    digest = hashlib.sha256(f"{seed}:{config_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


class PostgresDevMarketBootstrapRepository:
    def __init__(self, database_url: str, pricer: PreMarketPricer) -> None:
        self._database_url = database_url
        self._pricer = pricer

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def load_snapshot(self) -> StartupSnapshot:
        specs = {item.config_key: item for item in DEFAULT_ACTIVITY_PROFILES}
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                # Only the latest ingested season's players count towards the market's size.
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count FROM players
                    WHERE metadata ->> 'season' = (SELECT MAX(metadata ->> 'season') FROM players)
                    """
                )
                player_row = cursor.fetchone()
                if player_row is None:
                    raise DevMarketBootstrapError("could not count players")
                player_count = int(player_row["count"])
                cursor.execute(_INSTRUMENT_SIGNAL_SQL)
                signal_rows = cursor.fetchall()
                values = _stats_values(cursor)
                instruments = tuple(
                    _instrument_signal(row, values.get(str(row["player_id"])))
                    for row in signal_rows
                )
                cursor.execute(
                    """
                    SELECT c.config_key, c.config, COUNT(b.id) FILTER (
                               WHERE b.status = 'ACTIVE'
                           ) AS existing_count
                    FROM synthetic_trader_bot_configs AS c
                    LEFT JOIN synthetic_trader_bots AS b ON b.config_id = c.id
                    WHERE c.enabled = true AND c.config_key = ANY(%s)
                    GROUP BY c.id, c.config_key, c.config
                    """,
                    (list(specs),),
                )
                profile_rows = {str(row["config_key"]): row for row in cursor.fetchall()}
                profiles = tuple(
                    FleetProfileState(
                        spec=spec,
                        base_config=profile_rows[spec.config_key]["config"],
                        existing_count=int(profile_rows[spec.config_key]["existing_count"]),
                    )
                    for spec in DEFAULT_ACTIVITY_PROFILES
                    if spec.config_key in profile_rows
                )
                missing = sorted(set(specs) - {item.spec.config_key for item in profiles})
                if missing:
                    raise DevMarketBootstrapError(
                        "required synthetic trader configs are missing: " + ", ".join(missing)
                    )
                cursor.execute("SELECT EXISTS (SELECT 1 FROM synthetic_portfolio_bootstrap_batches)")
                bootstrap_row = cursor.fetchone()
                if bootstrap_row is None:
                    raise DevMarketBootstrapError("could not inspect portfolio bootstrap state")
                has_bootstrap = bool(bootstrap_row["exists"])
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM synthetic_trader_bots AS b
                    JOIN portfolios AS p ON p.account_id = b.account_id
                    WHERE b.status = 'ACTIVE' AND p.cash_balance <= 0
                    """
                )
                unfunded_row = cursor.fetchone()
                if unfunded_row is None:
                    raise DevMarketBootstrapError("could not count unfunded synthetic traders")
                unfunded = int(unfunded_row["count"])
        return StartupSnapshot(
            player_count=player_count,
            instruments=instruments,
            profiles=profiles,
            has_portfolio_bootstrap=has_bootstrap,
            unfunded_bot_count=unfunded,
        )

    def apply_valuations(
        self,
        valuations: Sequence[InstrumentValuation],
        options: ValuationOptions,
    ) -> int:
        if not valuations:
            return 0
        weights = Json(
            {
                "market_value": options.market_value_weight,
                "player_stats": options.stats_weight,
                "social_sentiment": options.social_weight,
            }
        )
        applied = 0
        with self._connection() as connection:
            for item in valuations:
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT 1 FROM dev_market_bootstrap_instrument_valuations
                            WHERE instrument_id = %s
                            """,
                            (str(item.instrument_id),),
                        )
                        if cursor.fetchone() is not None:
                            continue
                # Prices belong to the trading engine; it refuses instruments that have
                # already traded, which are simply left at their current price.
                try:
                    result = self._pricer.set_pre_market_price(
                        SetPreMarketPriceCommand(
                            request_id=f"pre-market-price:{item.instrument_id}:{item.new_price}",
                            instrument_id=item.instrument_id,
                            new_price=str(item.new_price),
                        )
                    )
                except TradingEngineClientError as exc:
                    if exc.body.get("code") == "instrument_has_market_activity":
                        continue
                    raise
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO dev_market_bootstrap_instrument_valuations (
                                instrument_id, old_price, new_price, anchor_price,
                                market_rank, stats_rank, social_rank, weights
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                str(item.instrument_id), Decimal(result.old_price),
                                item.new_price, item.anchor_price, item.market_rank,
                                item.stats_rank, item.social_rank, weights,
                            ),
                        )
                applied += 1
        return applied

    def apply_activity_overrides(self, profiles: Sequence[FleetProfilePlan]) -> int:
        overrides = {item.config_key: item.config_overrides for item in profiles}
        updated = 0
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT b.id, b.config_overrides, c.config_key
                        FROM synthetic_trader_bots AS b
                        JOIN synthetic_trader_bot_configs AS c ON c.id = b.config_id
                        WHERE b.status = 'ACTIVE' AND c.config_key = ANY(%s)
                        FOR UPDATE OF b
                        """,
                        (list(overrides),),
                    )
                    for row in cursor.fetchall():
                        config_key = str(row["config_key"])
                        merged = _deep_merge(row["config_overrides"], overrides[config_key])
                        cursor.execute(
                            """
                            UPDATE synthetic_trader_bots
                            SET config_overrides = %s, updated_at = now()
                            WHERE id = %s
                            """,
                            (Json(merged), str(row["id"])),
                        )
                        updated += 1
        return updated


class TradingEngineInstrumentSeeder:
    def __init__(self, client: HttpTradingEngineClient) -> None:
        self._client = client

    def seed(self) -> tuple[int, int]:
        result = self._client.seed_player_shares()
        return result.created_count, result.skipped_existing_count


class SyntheticFleetFundService:
    def __init__(
        self,
        repository: PostgresTopupRepository,
        service: TopupService,
    ) -> None:
        self._repository = repository
        self._service = service

    def fund(self, amount: Decimal) -> FundingResult:
        self._repository.ensure_active_synthetic_trader_policies(
            TopupCadence.WEEKLY,
            str(amount),
        )
        result = self._service.apply_topups(TopupCadence.WEEKLY, _utc_now())
        applied = sum(
            1 for item in result.outcomes if item.status is TopupOutcomeStatus.APPLIED
        )
        reused = sum(
            1 for item in result.outcomes if item.status is TopupOutcomeStatus.SKIPPED
        )
        failed = sum(
            1 for item in result.outcomes if item.status is TopupOutcomeStatus.FAILED
        )
        return FundingResult(
            planned=len(result.outcomes),
            applied=applied,
            reused=reused,
            failed=failed,
            applied_cash=amount * applied,
        )


class SyntheticPortfolioInitializer:
    def __init__(self, service: SyntheticPortfolioBootstrapService) -> None:
        self._service = service

    def initialize(
        self,
        *,
        seed: int,
        min_holders: int,
        max_positions_per_bot: int,
    ) -> PortfolioResult:
        result = self._service.bootstrap(
            all_active_synthetic_bots=True,
            seed=seed,
            min_holders_per_player=min_holders,
            max_player_supply_per_bot=Decimal("20"),
            reserve_supply_percent=Decimal("10"),
            max_positions_per_bot=max_positions_per_bot,
            dry_run=False,
        )
        return PortfolioResult(
            initialized=True,
            instruments=result.instruments_processed,
            positions=result.created_positions,
            skipped=len(result.skipped_instruments),
        )


def _utc_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _stats_values(cursor: Any) -> dict[str, float]:
    """Each player's per-90 contribution this season (see app.player_stats)."""
    now = _utc_now()
    return {
        player_id: stats_value(profile)
        for player_id, profile in load_stat_profiles(cursor, current_season(now), now.date()).items()
    }


def _instrument_signal(row: Mapping[str, Any], player_stats_value: float | None) -> InstrumentSignal:
    return InstrumentSignal(
        instrument_id=UUID(str(row["id"])),
        symbol=str(row["symbol"]),
        position=None if row["position"] is None else str(row["position"]),
        current_price=Decimal(str(row["current_price"])),
        market_value=None if row["market_value"] is None else float(row["market_value"]),
        stats_value=player_stats_value,
        social_value=None if row["social_value"] is None else float(row["social_value"]),
        recent_trade_count=int(row["recent_trade_count"]),
        has_activity=bool(row["has_activity"]),
        has_positions=bool(row["has_positions"]),
        already_valued=bool(row["already_valued"]),
    )


_INSTRUMENT_SIGNAL_SQL = """
    SELECT i.id, i.symbol, i.current_price, p.position,
           mv.value AS market_value,
           i.player_id::text AS player_id,
           social.social_value,
           COALESCE(activity.recent_trade_count, 0) AS recent_trade_count,
           EXISTS (SELECT 1 FROM orders WHERE instrument_id = i.id)
               OR EXISTS (SELECT 1 FROM trades WHERE instrument_id = i.id) AS has_activity,
           EXISTS (SELECT 1 FROM positions WHERE instrument_id = i.id) AS has_positions,
           EXISTS (
               SELECT 1 FROM dev_market_bootstrap_instrument_valuations
               WHERE instrument_id = i.id
           ) AS already_valued
    FROM instruments AS i
    JOIN players AS p ON p.id = i.player_id
    LEFT JOIN LATERAL (
        SELECT value FROM player_market_value_observations
        WHERE player_id = i.player_id AND currency = 'EUR'
        ORDER BY observed_at DESC, imported_at DESC, id DESC LIMIT 1
    ) AS mv ON true
    LEFT JOIN LATERAL (
        SELECT credibility_weighted_sentiment::double precision AS social_value
        FROM player_social_signal_snapshots WHERE player_id = i.player_id
        ORDER BY calculated_at DESC, id DESC LIMIT 1
    ) AS social ON true
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS recent_trade_count FROM trades
        WHERE instrument_id = i.id AND executed_at >= now() - interval '7 days'
    ) AS activity ON true
    WHERE i.instrument_type = 'PLAYER_SHARE' AND i.trading_status = 'ACTIVE'
    ORDER BY i.id
"""
