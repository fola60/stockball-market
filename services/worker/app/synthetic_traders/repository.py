from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import sqrt
from statistics import median
from threading import Lock
from typing import Any, Iterator, Mapping, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection
from app.player_stats import (
    RatingTotals,
    build_rating_profile,
    build_rating_profiles,
    league_median_rating,
    load_rating_totals,
    load_stat_profiles,
    rating_prior,
    stats_value,
)
from app.seasons import current_season

from .config_models import MAX_EVENT_WINDOW_HOURS
from .market_history import RollingMarketHistoryCache
from .models import (
    BettingMarketContext,
    BettingMarketQuote,
    BotActivityContext,
    BotPortfolioContext,
    BotPositionContext,
    BotStatus,
    CandidateInstrumentContext,
    CreateSyntheticTraderBotCommand,
    MarketTradeSample,
    MatchEventContext,
    PlayerStatsContext,
    PricePoint,
    SocialSignalContext,
    StrategyEngine,
    SyntheticTraderBotConfigRecord,
    SyntheticTraderBotRecord,
)
from .ranking import rank_percentiles as _percentiles

RECENT_MARKET_LOOKBACK_DAYS = 30
# A player's usual social attention comes from its latest snapshot covering at least a day,
# taken within the last week.
SOCIAL_BASELINE_MIN_LOOKBACK_SECONDS = 24 * 60 * 60
SOCIAL_BASELINE_MAX_AGE_DAYS = 7
MIN_EXPECTED_SOCIAL_MENTIONS = 1.0
# Bookmaker events are matched to a rated FotMob match by player and kickoff within this many
# seconds; providers round kickoff times differently and no fixture id is shared.
EVENT_KICKOFF_TOLERANCE_SECONDS = 3 * 60 * 60


class SyntheticTraderRepository(Protocol):
    def list_reserved_handles(self) -> set[str]: ...

    def list_due_bots(
        self,
        as_of: datetime,
        *,
        limit: int = 100,
        force_timing: bool = False,
        bot_ids: tuple[UUID, ...] = (),
    ) -> list[SyntheticTraderBotRecord]: ...

    def get_bot_config(self, config_id: UUID) -> SyntheticTraderBotConfigRecord | None: ...

    def get_bot_config_by_key(
        self,
        config_key: str,
    ) -> SyntheticTraderBotConfigRecord | None: ...

    def create_bot(
        self,
        command: CreateSyntheticTraderBotCommand,
    ) -> SyntheticTraderBotRecord: ...

    def load_portfolio_context(self, bot: SyntheticTraderBotRecord) -> BotPortfolioContext: ...

    def load_activity_context(
        self,
        bot: SyntheticTraderBotRecord,
        as_of: datetime,
    ) -> BotActivityContext: ...

    def load_candidate_instruments(
        self,
        portfolio: BotPortfolioContext,
        as_of: datetime,
        *,
        betting_lookback_minutes: int | None = None,
    ) -> tuple[CandidateInstrumentContext, ...]: ...

    def update_tick_state(
        self,
        bot_id: UUID,
        *,
        last_ticked_at: datetime,
        next_tick_after: datetime,
    ) -> None: ...


class PostgresSyntheticTraderRepository:
    def __init__(
        self,
        database_url: str,
        *,
        social_signals_enabled: bool = False,
        social_signal_max_age_seconds: int = 3600,
        match_rating_signals_enabled: bool = False,
    ) -> None:
        self._database_url = database_url
        self._social_signals_enabled = social_signals_enabled
        self._match_rating_signals_enabled = match_rating_signals_enabled
        self._social_signal_max_age_seconds = max(social_signal_max_age_seconds, 1)
        self._market_history = RollingMarketHistoryCache()
        self._market_history_refresh_lock = Lock()

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def set_bot_status(self, bot_ids: tuple[UUID, ...], status: BotStatus) -> int:
        if not bot_ids:
            return 0
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE synthetic_trader_bots
                    SET status = %(status)s, updated_at = now()
                    WHERE id = ANY(%(bot_ids)s::uuid[])
                    """,
                    {"status": status.value, "bot_ids": [str(bot_id) for bot_id in bot_ids]},
                )
                return cursor.rowcount

    def list_reserved_handles(self) -> set[str]:
        """Return all account handles so generated personas cannot collide with users."""
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT handle
                    FROM accounts
                    WHERE handle IS NOT NULL
                    """
                )
                rows = cursor.fetchall()
        return {str(row[0]).casefold() for row in rows}

    def list_due_bots(
        self,
        as_of: datetime,
        *,
        limit: int = 100,
        force_timing: bool = False,
        bot_ids: tuple[UUID, ...] = (),
    ) -> list[SyntheticTraderBotRecord]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        b.id,
                        b.account_id,
                        p.id AS portfolio_id,
                        b.config_id,
                        b.bot_key,
                        b.display_name,
                        b.status,
                        b.config_overrides,
                        b.last_ticked_at,
                        b.next_tick_after,
                        b.created_at,
                        b.updated_at
                    FROM synthetic_trader_bots AS b
                    JOIN accounts AS a
                        ON a.id = b.account_id
                    JOIN portfolios AS p
                        ON p.account_id = b.account_id
                    JOIN synthetic_trader_bot_configs AS c
                        ON c.id = b.config_id
                    WHERE b.status = 'ACTIVE'
                      AND a.account_type = 'SYNTHETIC_TRADER'
                      AND a.status = 'ACTIVE'
                      AND c.enabled = true
                      AND (%(all_bots)s OR b.id = ANY(%(bot_ids)s::uuid[]))
                      AND (
                        %(force_timing)s
                        OR
                        b.next_tick_after IS NULL
                        OR b.next_tick_after <= %(as_of)s
                      )
                    ORDER BY
                        COALESCE(b.next_tick_after, to_timestamp(0)),
                        b.created_at,
                        b.id
                    LIMIT %(limit)s
                    """,
                    {
                        "as_of": as_of,
                        "limit": limit,
                        "force_timing": force_timing,
                        "all_bots": not bot_ids,
                        "bot_ids": [str(bot_id) for bot_id in bot_ids],
                    },
                )
                rows = cursor.fetchall()

        return [_build_bot_record(row) for row in rows]

    def get_bot_config(self, config_id: UUID) -> SyntheticTraderBotConfigRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        config_key,
                        display_name,
                        strategy_engine,
                        version,
                        config,
                        enabled,
                        created_at,
                        updated_at
                    FROM synthetic_trader_bot_configs
                    WHERE id = %(config_id)s
                    """,
                    {"config_id": str(config_id)},
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _build_config_record(row)

    def get_bot_config_by_key(
        self,
        config_key: str,
    ) -> SyntheticTraderBotConfigRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        config_key,
                        display_name,
                        strategy_engine,
                        version,
                        config,
                        enabled,
                        created_at,
                        updated_at
                    FROM synthetic_trader_bot_configs
                    WHERE config_key = %(config_key)s
                      AND enabled = true
                    ORDER BY version DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    {"config_key": config_key},
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _build_config_record(row)

    def create_bot(
        self,
        command: CreateSyntheticTraderBotCommand,
    ) -> SyntheticTraderBotRecord:
        with self._connection() as connection:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO synthetic_trader_bots (
                            account_id,
                            config_id,
                            bot_key,
                            display_name,
                            status,
                            config_overrides
                        ) VALUES (
                            %(account_id)s,
                            %(config_id)s,
                            %(bot_key)s,
                            %(display_name)s,
                            %(status)s,
                            %(config_overrides)s::jsonb
                        )
                        RETURNING
                            id,
                            account_id,
                            config_id,
                            bot_key,
                            display_name,
                            status,
                            config_overrides,
                            last_ticked_at,
                            next_tick_after,
                            created_at,
                            updated_at
                        """,
                        {
                            "account_id": str(command.account_id),
                            "config_id": str(command.config_id),
                            "bot_key": command.bot_key,
                            "display_name": command.display_name,
                            "status": command.status.value,
                            "config_overrides": _json_object(command.config_overrides),
                        },
                    )
                    row = cursor.fetchone()
                    return _build_bot_record(
                        {
                            **row,
                            "portfolio_id": self._get_portfolio_id(cursor, command.account_id),
                        }
                    )

    def load_portfolio_context(self, bot: SyntheticTraderBotRecord) -> BotPortfolioContext:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        account_id,
                        cash_balance
                    FROM portfolios
                    WHERE id = %(portfolio_id)s
                    """,
                    {"portfolio_id": str(bot.portfolio_id)},
                )
                portfolio_row = cursor.fetchone()
                if portfolio_row is None:
                    raise LookupError(f"portfolio {bot.portfolio_id} was not found")

                cursor.execute(
                    """
                    SELECT
                        p.instrument_id,
                        i.player_id,
                        player.club,
                        p.quantity,
                        i.current_price,
                        latest_trade.execution_price AS last_trade_price,
                        latest_trade.executed_at AS last_trade_at,
                        basis.events AS cost_events
                    FROM positions AS p
                    JOIN instruments AS i
                        ON i.id = p.instrument_id
                    LEFT JOIN players AS player
                        ON player.id = i.player_id
                    LEFT JOIN LATERAL (
                        SELECT execution_price, executed_at
                        FROM trades
                        WHERE portfolio_id = %(portfolio_id)s
                          AND instrument_id = p.instrument_id
                        ORDER BY executed_at DESC, id DESC
                        LIMIT 1
                    ) AS latest_trade
                        ON true
                    LEFT JOIN LATERAL (
                        SELECT jsonb_agg(jsonb_build_object('side', side, 'quantity', quantity::text,
                            'gross_amount', gross_amount::text) ORDER BY occurred_at, event_id) AS events
                        FROM (
                            SELECT side, shares AS quantity, gross_amount, executed_at AS occurred_at, id AS event_id
                            FROM trades WHERE portfolio_id = p.portfolio_id AND instrument_id = p.instrument_id
                            UNION ALL
                            SELECT 'BUY', quantity, quantity * seed_price, created_at, id
                            FROM synthetic_portfolio_bootstrap_allocations
                            WHERE portfolio_id = p.portfolio_id AND instrument_id = p.instrument_id
                        ) AS events
                    ) AS basis ON true
                    WHERE p.portfolio_id = %(portfolio_id)s
                      AND p.quantity > 0
                    ORDER BY p.updated_at DESC, p.instrument_id
                    """,
                    {"portfolio_id": str(bot.portfolio_id)},
                )
                position_rows = cursor.fetchall()

        positions = tuple(_build_position_context(row) for row in position_rows)
        total_position_value = sum((position.market_value for position in positions), Decimal("0"))
        cash_balance = _decimal(portfolio_row["cash_balance"])
        return BotPortfolioContext(
            account_id=bot.account_id,
            portfolio_id=bot.portfolio_id,
            cash_balance=cash_balance,
            total_position_value=total_position_value,
            total_equity=cash_balance + total_position_value,
            positions=positions,
        )

    def _get_portfolio_id(self, cursor, account_id: UUID) -> UUID:
        cursor.execute(
            """
            SELECT id
            FROM portfolios
            WHERE account_id = %(account_id)s
            """,
            {"account_id": str(account_id)},
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError(f"portfolio for account {account_id} was not found")
        return UUID(str(row["id"]))

    def load_activity_context(
        self,
        bot: SyntheticTraderBotRecord,
        as_of: datetime,
    ) -> BotActivityContext:
        day_start = _day_start(as_of)
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS trade_count,
                        COALESCE(SUM(gross_amount), 0) AS turnover_cash,
                        MAX(executed_at) AS last_order_at
                    FROM trades
                    WHERE account_id = %(account_id)s
                      AND executed_at >= %(day_start)s
                    """,
                    {"account_id": str(bot.account_id), "day_start": day_start},
                )
                row = cursor.fetchone()

        return BotActivityContext(
            daily_trade_count=int(row["trade_count"]),
            daily_turnover_cash=_decimal(row["turnover_cash"]),
            last_order_at=row["last_order_at"],
        )

    def load_candidate_instruments(
        self,
        portfolio: BotPortfolioContext,
        as_of: datetime,
        *,
        betting_lookback_minutes: int | None = None,
    ) -> tuple[CandidateInstrumentContext, ...]:
        market_since = as_of - timedelta(days=RECENT_MARKET_LOOKBACK_DAYS)
        holdings = {position.instrument_id: position for position in portfolio.positions}

        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.id,
                        i.player_id,
                        i.symbol,
                        i.reference_price,
                        upcoming.fixture_count,
                        i.display_name,
                        i.current_price,
                        i.trading_status,
                        player.club,
                        player.position
                    FROM instruments AS i
                    LEFT JOIN players AS player
                        ON player.id = i.player_id
                    LEFT JOIN LATERAL (
                        SELECT COUNT(DISTINCT (home_team_name, away_team_name, kickoff_at)) AS fixture_count
                        FROM fixtures
                        WHERE (lower(home_team_name) = lower(player.club) OR lower(away_team_name) = lower(player.club))
                          AND kickoff_at > %(as_of)s AND kickoff_at <= %(as_of)s + interval '7 days'
                          AND COALESCE(status_short, '') NOT IN ('PST', 'CANC', 'ABD')
                    ) AS upcoming ON true
                    WHERE i.instrument_type = 'PLAYER_SHARE'
                    ORDER BY i.created_at DESC, i.id DESC
                    """,
                    {"as_of": as_of},
                )
                instrument_rows = cursor.fetchall()

                instrument_ids = [str(row["id"]) for row in instrument_rows]
                player_ids = [
                    str(row["player_id"]) for row in instrument_rows if row["player_id"] is not None
                ]
                prices_by_instrument = self._load_prices(
                    cursor, instrument_ids, market_since, as_of
                )
                trades_by_instrument = self._load_trades(
                    cursor, instrument_ids, market_since, as_of
                )
                market_values_by_player = self._load_market_values(cursor, player_ids)
                stats_by_player, events_by_player = self._load_stats(cursor, player_ids, as_of)
                betting_by_player = (
                    {}
                    if betting_lookback_minutes is None
                    else self._load_betting_markets(
                        cursor,
                        player_ids,
                        as_of - timedelta(minutes=betting_lookback_minutes),
                        as_of,
                    )
                )
                social_by_player = self._load_social(cursor, player_ids, as_of)

        candidates: list[CandidateInstrumentContext] = []
        for row in instrument_rows:
            instrument_id = UUID(str(row["id"]))
            player_id = None if row["player_id"] is None else UUID(str(row["player_id"]))
            current_price = _decimal(row["current_price"])
            price_points = list(prices_by_instrument.get(str(instrument_id), ()))
            if not price_points or price_points[-1].price != current_price:
                price_points.append(PricePoint(price=current_price, captured_at=as_of))
            holding = holdings.get(instrument_id)
            market_value_record = (
                None if player_id is None else market_values_by_player.get(str(player_id))
            )
            candidates.append(
                CandidateInstrumentContext(
                    instrument_id=instrument_id,
                    player_id=player_id,
                    symbol=str(row["symbol"]),
                    fixture_score=max(-1.0, 1.0 - 0.5 * (int(row.get("fixture_count") or 0) - 1))
                    if row.get("fixture_count")
                    else 0.0,
                    reference_price=_decimal(row["reference_price"])
                    if row.get("reference_price") is not None
                    else None,
                    display_name=str(row["display_name"]),
                    club=None if row["club"] is None else str(row["club"]),
                    position=None if row["position"] is None else str(row["position"]),
                    current_price=current_price,
                    trading_status=str(row["trading_status"]),
                    current_holding_quantity=(
                        Decimal("0") if holding is None else holding.quantity
                    ),
                    current_holding_value=(
                        Decimal("0") if holding is None else holding.market_value
                    ),
                    market_value_observation=(
                        None if market_value_record is None else market_value_record[0]
                    ),
                    market_value_observed_at=(
                        None if market_value_record is None else market_value_record[1]
                    ),
                    recent_prices=tuple(price_points),
                    recent_trades=tuple(trades_by_instrument.get(str(instrument_id), ())),
                    stats=(
                        PlayerStatsContext()
                        if player_id is None
                        else stats_by_player.get(str(player_id), PlayerStatsContext())
                    ),
                    social=(
                        SocialSignalContext()
                        if player_id is None
                        else social_by_player.get(str(player_id), SocialSignalContext())
                    ),
                    betting=(
                        BettingMarketContext()
                        if player_id is None
                        else betting_by_player.get(str(player_id), BettingMarketContext())
                    ),
                    match_event=None if player_id is None else events_by_player.get(str(player_id)),
                )
            )

        return tuple(candidates)

    def update_tick_state(
        self,
        bot_id: UUID,
        *,
        last_ticked_at: datetime,
        next_tick_after: datetime,
    ) -> None:
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE synthetic_trader_bots
                        SET
                            last_ticked_at = %(last_ticked_at)s,
                            next_tick_after = %(next_tick_after)s,
                            updated_at = now()
                        WHERE id = %(bot_id)s
                        """,
                        {
                            "bot_id": str(bot_id),
                            "last_ticked_at": last_ticked_at,
                            "next_tick_after": next_tick_after,
                        },
                    )

    def _load_prices(
        self,
        cursor,
        instrument_ids: list[str],
        market_since: datetime,
        as_of: datetime,
    ) -> dict[str, list[PricePoint]]:
        if not instrument_ids:
            return {}
        instrument_uuids = [UUID(instrument_id) for instrument_id in instrument_ids]
        with self._market_history_refresh_lock:
            query_since = self._market_history.next_price_since(market_since, as_of)
            if query_since is not None:
                cursor.execute(
                    """
                    SELECT
                        id,
                        instrument_id,
                        new_price,
                        captured_at
                    FROM price_snapshots
                    WHERE instrument_id = ANY(%(instrument_ids)s::uuid[])
                      AND captured_at >= %(query_since)s
                      AND captured_at <= %(as_of)s
                    ORDER BY captured_at ASC, id ASC
                    """,
                    {
                        "instrument_ids": instrument_ids,
                        "query_since": query_since,
                        "as_of": as_of,
                    },
                )
                self._market_history.record_prices(
                    cursor.fetchall(),
                    window_start=market_since,
                    scanned_through=as_of,
                )
            return self._market_history.prices(
                instrument_uuids,
                window_start=market_since,
                through=as_of,
            )

    def _load_trades(
        self,
        cursor,
        instrument_ids: list[str],
        market_since: datetime,
        as_of: datetime,
    ) -> dict[str, list[MarketTradeSample]]:
        if not instrument_ids:
            return {}
        instrument_uuids = [UUID(instrument_id) for instrument_id in instrument_ids]
        with self._market_history_refresh_lock:
            query_since = self._market_history.next_trade_since(market_since, as_of)
            if query_since is not None:
                cursor.execute(
                    """
                    SELECT
                        id,
                        instrument_id,
                        side,
                        shares,
                        gross_amount,
                        account_id,
                        executed_at
                    FROM trades
                    WHERE instrument_id = ANY(%(instrument_ids)s::uuid[])
                      AND executed_at >= %(query_since)s
                      AND executed_at <= %(as_of)s
                    ORDER BY executed_at ASC, id ASC
                    """,
                    {
                        "instrument_ids": instrument_ids,
                        "query_since": query_since,
                        "as_of": as_of,
                    },
                )
                self._market_history.record_trades(
                    cursor.fetchall(),
                    window_start=market_since,
                    scanned_through=as_of,
                )
            return self._market_history.trades(
                instrument_uuids,
                window_start=market_since,
                through=as_of,
            )

    def _load_market_values(
        self,
        cursor,
        player_ids: list[str],
    ) -> dict[str, tuple[Decimal, datetime]]:
        if not player_ids:
            return {}
        cursor.execute(
            """
            SELECT DISTINCT ON (player_id)
                player_id::text AS player_id,
                value,
                observed_at
            FROM player_market_value_observations
            WHERE player_id = ANY(%(player_ids)s::uuid[])
            ORDER BY player_id, observed_at DESC, id DESC
            """,
            {"player_ids": player_ids},
        )
        rows = cursor.fetchall()
        return {str(row["player_id"]): (_decimal(row["value"]), row["observed_at"]) for row in rows}

    def _load_stats(
        self,
        cursor,
        player_ids: list[str],
        as_of: datetime,
    ) -> tuple[dict[str, PlayerStatsContext], dict[str, MatchEventContext]]:
        if not player_ids:
            return {}, {}
        season = current_season(as_of)
        profiles = load_stat_profiles(cursor, season, as_of.date())
        strengths = _percentiles(
            {player_id: stats_value(profile) for player_id, profile in profiles.items()}
        )
        ratings = {}
        rating_strengths = {}
        events: dict[str, MatchEventContext] = {}
        if self._match_rating_signals_enabled:
            current, previous = load_rating_totals(cursor, season, as_of)
            ratings = build_rating_profiles(season, current, previous)
            rating_strengths = _percentiles(
                {player_id: profile.rating for player_id, profile in ratings.items()}
            )
            league = league_median_rating(previous.values()) or league_median_rating(
                current.values()
            )
            if league is not None:
                events = self._load_match_events(
                    cursor, player_ids, as_of, season, current, previous, league
                )
        wanted = set(player_ids)
        stats: dict[str, PlayerStatsContext] = {}
        for player_id in (profiles.keys() | ratings.keys()) & wanted:
            profile = profiles.get(player_id)
            rating = ratings.get(player_id)
            rating_fields = (
                {}
                if rating is None
                else {
                    "average_rating": rating.rating,
                    "rating_strength": rating_strengths[player_id] * 2.0 - 1.0,
                    "rated_nineties": rating.rated_nineties,
                    "rating_form": rating.form,
                }
            )
            if profile is None:
                # No FBref snapshot: no per-90 rates to count, observed zero or otherwise.
                stats[player_id] = PlayerStatsContext(available_rates=frozenset(), **rating_fields)
                continue
            stats[player_id] = PlayerStatsContext(
                available_rates=profile.available_rates,
                latest_observed_at=profile.latest_observed_at,
                games=profile.games,
                minutes_per_game=profile.minutes_per_game,
                goals_per90=profile.goals_per90,
                assists_per90=profile.assists_per90,
                shots_per90=profile.shots_per90,
                key_passes_per90=profile.key_passes_per90,
                defensive_actions_per90=profile.defensive_actions_per90,
                cards_per90=profile.cards_per90,
                clean_sheets_per_game=profile.clean_sheets_per_game,
                recent_minutes=profile.recent_minutes,
                recent_goal_involvements_per90=profile.recent_goal_involvements_per90,
                recent_defensive_actions_per90=profile.recent_defensive_actions_per90,
                strength=strengths[player_id] * 2.0 - 1.0,
                **rating_fields,
            )
        return stats, events

    def _load_match_events(
        self,
        cursor,
        player_ids: list[str],
        as_of: datetime,
        season: int,
        current: Mapping[str, RatingTotals],
        previous: Mapping[str, RatingTotals],
        league: float,
    ) -> dict[str, MatchEventContext]:
        """Each player's latest rated match this season whose ratings were known by `as_of`.

        A backfill stamps old matches with the time it ran, so the match must also have kicked
        off within the window: archived matches never read as fresh events.
        """
        window_start = as_of - timedelta(hours=MAX_EVENT_WINDOW_HOURS)
        cursor.execute(
            """
            SELECT DISTINCT ON (r.player_id)
                r.player_id::text AS player_id,
                m.match_id,
                m.kickoff_at,
                r.rating::float8 AS rating,
                r.minutes_played,
                r.team_name,
                CASE WHEN r.team_provider_id = m.home_team_id
                     THEN m.away_team_name ELSE m.home_team_name END AS opponent_name,
                known.known_at
            FROM player_match_ratings AS r
            JOIN fotmob_matches AS m ON m.match_id = r.provider_match_id
            JOIN LATERAL (
                SELECT min(observed_at) AS known_at
                FROM player_match_ratings
                WHERE provider = r.provider AND provider_match_id = r.provider_match_id
            ) AS known ON true
            WHERE r.player_id = ANY(%(player_ids)s::uuid[])
              AND r.rating IS NOT NULL
              AND COALESCE(r.minutes_played, 0) > 0
              AND m.season = %(season)s
              AND m.kickoff_at >= %(kickoff_after)s
              AND m.kickoff_at <= %(as_of)s
              AND known.known_at >= %(window_start)s
              AND known.known_at <= %(as_of)s
            ORDER BY r.player_id, m.kickoff_at DESC, m.match_id DESC
            """,
            {
                "player_ids": player_ids,
                "season": season,
                # Ratings follow full time by at least a quarter of an hour.
                "kickoff_after": window_start - timedelta(hours=3),
                "window_start": window_start,
                "as_of": as_of,
            },
        )
        rows = cursor.fetchall()
        if not rows:
            return {}
        closing = self._load_closing_quotes(cursor, rows, as_of)
        events: dict[str, MatchEventContext] = {}
        for row in rows:
            player_id = str(row["player_id"])
            nineties = min(int(row["minutes_played"]), 90) / 90.0
            season_totals = current.get(player_id, RatingTotals())
            baseline = build_rating_profile(
                season,
                season_totals.without(float(row["rating"]), nineties),
                rating_prior(previous.get(player_id), league),
            )
            events[player_id] = MatchEventContext(
                provider_match_id=str(row["match_id"]),
                kickoff_at=row["kickoff_at"],
                known_at=row["known_at"],
                rating=float(row["rating"]),
                minutes_played=int(row["minutes_played"]),
                baseline_rating=baseline.rating,
                baseline_nineties=baseline.rated_nineties,
                team_name=row["team_name"],
                opponent_name=row["opponent_name"],
                closing_quotes=tuple(closing.get(player_id, ())),
            )
        return events

    def _load_closing_quotes(
        self, cursor, events: list[Mapping[str, Any]], as_of: datetime
    ) -> dict[str, list[BettingMarketQuote]]:
        """Each player's last pre-kickoff quote per selection for his rated match."""
        cursor.execute(
            """
            SELECT DISTINCT ON (participant.player_id, selection.id)
                participant.player_id::text AS player_id,
                selection.provider_event_id,
                selection.canonical_selection_key,
                selection.market_type,
                selection.outcome_type,
                selection.line,
                observation.decimal_odds,
                observation.implied_probability,
                observation.observed_at,
                (selection.raw_payload ->> 'kickoff_at')::timestamptz AS kickoff_at
            FROM unnest(%(player_ids)s::uuid[], %(kickoffs)s::timestamptz[])
                AS event(player_id, kickoff_at)
            JOIN betting_market_selection_players AS participant
                ON participant.player_id = event.player_id
            JOIN betting_market_selections AS selection
                ON selection.id = participant.selection_id
            JOIN betting_market_observations AS observation
                ON observation.selection_id = selection.id
            WHERE participant.participant_role = 'PRIMARY'
              AND selection.market_scope = 'PLAYER'
              AND abs(extract(epoch FROM (
                    (selection.raw_payload ->> 'kickoff_at')::timestamptz - event.kickoff_at
                  ))) <= %(tolerance)s
              AND observation.observed_at < (selection.raw_payload ->> 'kickoff_at')::timestamptz
              AND observation.observed_at <= %(as_of)s
            ORDER BY participant.player_id, selection.id,
                     observation.observed_at DESC, observation.id DESC
            """,
            {
                "player_ids": [str(row["player_id"]) for row in events],
                "kickoffs": [row["kickoff_at"] for row in events],
                "tolerance": EVENT_KICKOFF_TOLERANCE_SECONDS,
                "as_of": as_of,
            },
        )
        grouped: dict[str, list[BettingMarketQuote]] = {}
        for row in cursor.fetchall():
            grouped.setdefault(str(row["player_id"]), []).append(
                BettingMarketQuote(
                    provider_event_id=str(row["provider_event_id"]),
                    canonical_selection_key=str(row["canonical_selection_key"]),
                    market_type=str(row["market_type"]),
                    outcome_type=str(row["outcome_type"]),
                    line=None if row["line"] is None else _decimal(row["line"]),
                    decimal_odds=_decimal(row["decimal_odds"]),
                    implied_probability=_decimal(row["implied_probability"]),
                    observed_at=row["observed_at"],
                    kickoff_at=row["kickoff_at"],
                )
            )
        return grouped

    def _load_social(
        self, cursor, player_ids: list[str], as_of: datetime
    ) -> dict[str, SocialSignalContext]:
        if not player_ids or not self._social_signals_enabled:
            return {}
        cursor.execute(
            """
            SELECT DISTINCT ON (player_id)
                player_id::text AS player_id,
                lookback_seconds,
                trusted_mention_count,
                credibility_weighted_sentiment,
                injury_confirmation_count,
                mention_velocity,
                corroborating_source_count,
                signal_confidence,
                calculated_at
            FROM player_social_signal_snapshots
            WHERE player_id = ANY(%(player_ids)s::uuid[])
              AND lookback_seconds = 3600
              AND calculated_at <= %(as_of)s
              AND calculated_at >= %(fresh_after)s
            ORDER BY player_id, calculated_at DESC, lookback_seconds ASC
            """,
            {
                "player_ids": player_ids,
                "as_of": as_of,
                "fresh_after": as_of - timedelta(seconds=self._social_signal_max_age_seconds),
            },
        )
        latest_rows = cursor.fetchall()
        if not latest_rows:
            return {}
        # Each player's usual hourly attention, from its most recent long-window snapshot.
        cursor.execute(
            """
            SELECT DISTINCT ON (player_id)
                player_id::text AS player_id,
                trusted_mention_count,
                lookback_seconds
            FROM player_social_signal_snapshots
            WHERE player_id = ANY(%(player_ids)s::uuid[])
              AND lookback_seconds >= %(min_baseline_seconds)s
              AND calculated_at <= %(as_of)s
              AND calculated_at >= %(baseline_after)s
            ORDER BY player_id, calculated_at DESC, lookback_seconds DESC
            """,
            {
                "player_ids": [str(row["player_id"]) for row in latest_rows],
                "min_baseline_seconds": SOCIAL_BASELINE_MIN_LOOKBACK_SECONDS,
                "as_of": as_of,
                "baseline_after": as_of - timedelta(days=SOCIAL_BASELINE_MAX_AGE_DAYS),
            },
        )
        baseline_rates = {
            str(row["player_id"]): int(row["trusted_mention_count"])
            / (int(row["lookback_seconds"]) / 3600)
            for row in cursor.fetchall()
        }
        # Players with no history of their own are compared with a typical player.
        league_rate = median(baseline_rates.values()) if baseline_rates else 0.0
        return {
            str(row["player_id"]): SocialSignalContext(
                baseline_available=bool(baseline_rates),
                mention_count=int(row["trusted_mention_count"]),
                mention_velocity=float(row["mention_velocity"]),
                mention_spike_zscore=_mention_spike_zscore(
                    int(row["trusted_mention_count"]),
                    int(row["lookback_seconds"]) / 3600,
                    baseline_rates.get(str(row["player_id"]), league_rate),
                )
                if baseline_rates
                else 0.0,
                sentiment_score=(
                    0.0
                    if row["credibility_weighted_sentiment"] is None
                    else float(row["credibility_weighted_sentiment"])
                ),
                news_count=int(row["corroborating_source_count"]),
                trusted_news_count=int(row["corroborating_source_count"]),
                injury_count=int(row["injury_confirmation_count"]),
                source_credibility=float(row["signal_confidence"]),
                latest_observed_at=row["calculated_at"],
            )
            for row in latest_rows
        }

    def _load_betting_markets(
        self,
        cursor,
        player_ids: list[str],
        betting_since: datetime,
        as_of: datetime,
    ) -> dict[str, BettingMarketContext]:
        if not player_ids:
            return {}
        cursor.execute(
            """
            SELECT
                player_id,
                provider_event_id,
                canonical_selection_key,
                market_type,
                outcome_type,
                line,
                decimal_odds,
                implied_probability,
                observed_at,
                kickoff_at,
                observation_count
            FROM (
                SELECT
                    participant.player_id::text AS player_id,
                    selection.provider_event_id,
                    selection.canonical_selection_key,
                    selection.market_type,
                    selection.outcome_type,
                    selection.line,
                    observation.decimal_odds,
                    observation.implied_probability,
                    observation.observed_at,
                    (selection.raw_payload ->> 'kickoff_at')::timestamptz AS kickoff_at,
                    COUNT(*) OVER (
                        PARTITION BY participant.player_id, selection.id
                    ) AS observation_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY participant.player_id, selection.id
                        ORDER BY observation.observed_at DESC, observation.id DESC
                    ) AS latest_row_number,
                    ROW_NUMBER() OVER (
                        PARTITION BY participant.player_id, selection.id
                        ORDER BY observation.observed_at ASC, observation.id ASC
                    ) AS baseline_row_number
                FROM betting_market_selection_players AS participant
                JOIN betting_market_selections AS selection
                    ON selection.id = participant.selection_id
                JOIN betting_market_observations AS observation
                    ON observation.selection_id = selection.id
                WHERE participant.player_id = ANY(%(player_ids)s::uuid[])
                  AND participant.participant_role = 'PRIMARY'
                  AND selection.market_scope = 'PLAYER'
                  AND observation.observed_at >= %(betting_since)s
                  AND observation.observed_at <= %(as_of)s
            ) AS ranked
            WHERE latest_row_number = 1
               OR baseline_row_number = 1
            ORDER BY player_id, canonical_selection_key, observed_at ASC
            """,
            {
                "player_ids": player_ids,
                "betting_since": betting_since,
                "as_of": as_of,
            },
        )
        grouped: dict[str, list[BettingMarketQuote]] = {}
        for row in cursor.fetchall():
            grouped.setdefault(str(row["player_id"]), []).append(
                BettingMarketQuote(
                    provider_event_id=str(row["provider_event_id"]),
                    canonical_selection_key=str(row["canonical_selection_key"]),
                    market_type=str(row["market_type"]),
                    outcome_type=str(row["outcome_type"]),
                    line=None if row["line"] is None else _decimal(row["line"]),
                    decimal_odds=_decimal(row["decimal_odds"]),
                    implied_probability=_decimal(row["implied_probability"]),
                    observed_at=row["observed_at"],
                    kickoff_at=row["kickoff_at"],
                    observation_count=int(row["observation_count"]),
                )
            )
        return {
            player_id: BettingMarketContext(quotes=tuple(quotes))
            for player_id, quotes in grouped.items()
        }


def _mention_spike_zscore(observed: int, window_hours: float, baseline_hourly_rate: float) -> float:
    """How unusual this window's mentions are for the player, as a Poisson z-score against
    its usual rate. The expected count is floored so a single mention of a usually-quiet
    player reads as notable rather than extreme."""
    expected = baseline_hourly_rate * window_hours
    return (observed - expected) / sqrt(max(expected, MIN_EXPECTED_SOCIAL_MENTIONS))


def _build_bot_record(row: Mapping[str, Any]) -> SyntheticTraderBotRecord:
    return SyntheticTraderBotRecord(
        id=UUID(str(row["id"])),
        account_id=UUID(str(row["account_id"])),
        portfolio_id=UUID(str(row["portfolio_id"])),
        config_id=UUID(str(row["config_id"])),
        bot_key=str(row["bot_key"]),
        display_name=str(row["display_name"]),
        status=BotStatus(str(row["status"])),
        config_overrides=_mapping_dict(row["config_overrides"]),
        last_ticked_at=row["last_ticked_at"],
        next_tick_after=row["next_tick_after"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_config_record(row: Mapping[str, Any]) -> SyntheticTraderBotConfigRecord:
    return SyntheticTraderBotConfigRecord(
        id=UUID(str(row["id"])),
        config_key=str(row["config_key"]),
        display_name=str(row["display_name"]),
        strategy_engine=StrategyEngine(str(row["strategy_engine"])),
        version=int(row["version"]),
        config=_mapping_dict(row["config"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_position_context(row: Mapping[str, Any]) -> BotPositionContext:
    quantity = _decimal(row["quantity"])
    current_price = _decimal(row["current_price"])
    market_value = quantity * current_price
    last_trade_price = (
        None if row["last_trade_price"] is None else _decimal(row["last_trade_price"])
    )
    unrealized_return_pct = None
    average_cost = _average_cost(row.get("cost_events") or (), quantity)
    if average_cost is not None and average_cost > 0:
        unrealized_return_pct = float((current_price - average_cost) / average_cost)
    return BotPositionContext(
        instrument_id=UUID(str(row["instrument_id"])),
        player_id=None if row["player_id"] is None else UUID(str(row["player_id"])),
        club=None if row["club"] is None else str(row["club"]),
        quantity=quantity,
        current_price=current_price,
        market_value=market_value,
        last_trade_price=last_trade_price,
        unrealized_return_pct=unrealized_return_pct,
        last_trade_at=row.get("last_trade_at"),
    )


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _mapping_dict(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _json_object(value: Mapping[str, Any] | None) -> str:
    if value is None:
        return "{}"
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))


def _day_start(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    normalized = normalized.astimezone(UTC)
    return normalized.replace(hour=0, minute=0, second=0, microsecond=0)


def _average_cost(events, expected_quantity):
    quantity = Decimal("0")
    cost = Decimal("0")
    for event in events:
        amount = Decimal(str(event["quantity"]))
        if event["side"] == "BUY":
            quantity += amount
            cost += Decimal(str(event["gross_amount"]))
        elif quantity >= amount and quantity > 0:
            cost *= (quantity - amount) / quantity
            quantity -= amount
        else:
            return None
    return cost / quantity if quantity > 0 and quantity == expected_quantity else None
