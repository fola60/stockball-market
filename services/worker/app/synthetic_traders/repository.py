from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import fmean
from typing import Any, Iterator, Mapping, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.clients.trading_engine import OrderSide
from app.database import connection as pooled_connection

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
    PlayerStatsContext,
    PricePoint,
    SocialSignalContext,
    StrategyEngine,
    SyntheticTraderBotConfigRecord,
    SyntheticTraderBotRecord,
)

RECENT_MARKET_LOOKBACK_DAYS = 30
RECENT_STATS_LOOKBACK_DAYS = 180
MAX_STATS_ROWS_PER_PLAYER = 20


class SyntheticTraderRepository(Protocol):
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
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

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
                        latest_trade.execution_price AS last_trade_price
                    FROM positions AS p
                    JOIN instruments AS i
                        ON i.id = p.instrument_id
                    LEFT JOIN players AS player
                        ON player.id = i.player_id
                    LEFT JOIN LATERAL (
                        SELECT execution_price
                        FROM trades
                        WHERE portfolio_id = %(portfolio_id)s
                          AND instrument_id = p.instrument_id
                        ORDER BY executed_at DESC, id DESC
                        LIMIT 1
                    ) AS latest_trade
                        ON true
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
        stats_since = as_of - timedelta(days=RECENT_STATS_LOOKBACK_DAYS)
        holdings = {position.instrument_id: position for position in portfolio.positions}

        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.id,
                        i.player_id,
                        i.symbol,
                        i.display_name,
                        i.current_price,
                        i.trading_status,
                        player.club,
                        player.position
                    FROM instruments AS i
                    LEFT JOIN players AS player
                        ON player.id = i.player_id
                    WHERE i.instrument_type = 'PLAYER_SHARE'
                    ORDER BY i.created_at DESC, i.id DESC
                    """
                )
                instrument_rows = cursor.fetchall()

                instrument_ids = [str(row["id"]) for row in instrument_rows]
                player_ids = [
                    str(row["player_id"])
                    for row in instrument_rows
                    if row["player_id"] is not None
                ]
                prices_by_instrument = self._load_prices(cursor, instrument_ids, market_since)
                trades_by_instrument = self._load_trades(cursor, instrument_ids, market_since)
                market_values_by_player = self._load_market_values(cursor, player_ids)
                stats_by_player = self._load_stats(cursor, player_ids, stats_since)
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
                social_by_player = self._load_social(player_ids)

        candidates: list[CandidateInstrumentContext] = []
        for row in instrument_rows:
            instrument_id = UUID(str(row["id"]))
            player_id = (
                None if row["player_id"] is None else UUID(str(row["player_id"]))
            )
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
    ) -> dict[str, list[PricePoint]]:
        if not instrument_ids:
            return {}
        cursor.execute(
            """
            SELECT
                instrument_id::text AS instrument_id,
                new_price,
                captured_at
            FROM price_snapshots
            WHERE instrument_id = ANY(%(instrument_ids)s::uuid[])
              AND captured_at >= %(market_since)s
            ORDER BY instrument_id, captured_at ASC, id ASC
            """,
            {"instrument_ids": instrument_ids, "market_since": market_since},
        )
        rows = cursor.fetchall()
        prices: dict[str, list[PricePoint]] = {}
        for row in rows:
            prices.setdefault(str(row["instrument_id"]), []).append(
                PricePoint(
                    price=_decimal(row["new_price"]),
                    captured_at=row["captured_at"],
                )
            )
        return prices

    def _load_trades(
        self,
        cursor,
        instrument_ids: list[str],
        market_since: datetime,
    ) -> dict[str, list[MarketTradeSample]]:
        if not instrument_ids:
            return {}
        cursor.execute(
            """
            SELECT
                instrument_id::text AS instrument_id,
                side,
                shares,
                gross_amount,
                account_id,
                executed_at
            FROM trades
            WHERE instrument_id = ANY(%(instrument_ids)s::uuid[])
              AND executed_at >= %(market_since)s
            ORDER BY instrument_id, executed_at ASC, id ASC
            """,
            {"instrument_ids": instrument_ids, "market_since": market_since},
        )
        rows = cursor.fetchall()
        trades: dict[str, list[MarketTradeSample]] = {}
        for row in rows:
            trades.setdefault(str(row["instrument_id"]), []).append(
                MarketTradeSample(
                    instrument_id=UUID(str(row["instrument_id"])),
                    side=OrderSide(str(row["side"])),
                    quantity=_decimal(row["shares"]),
                    gross_amount=_decimal(row["gross_amount"]),
                    account_id=UUID(str(row["account_id"])),
                    executed_at=row["executed_at"],
                )
            )
        return trades

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
        return {
            str(row["player_id"]): (_decimal(row["value"]), row["observed_at"])
            for row in rows
        }

    def _load_stats(
        self,
        cursor,
        player_ids: list[str],
        stats_since: datetime,
    ) -> dict[str, PlayerStatsContext]:
        if not player_ids:
            return {}
        cursor.execute(
            """
            SELECT
                player_id::text AS player_id,
                rating,
                stats,
                observed_at
            FROM (
                SELECT
                    player_id,
                    rating,
                    stats,
                    observed_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_id
                        ORDER BY observed_at DESC, id DESC
                    ) AS row_number
                FROM player_stat_observations
                WHERE player_id = ANY(%(player_ids)s::uuid[])
                  AND observed_at >= %(stats_since)s
            ) AS ranked
            WHERE row_number <= %(max_rows)s
            ORDER BY player_id, observed_at DESC
            """,
            {
                "player_ids": player_ids,
                "stats_since": stats_since,
                "max_rows": MAX_STATS_ROWS_PER_PLAYER,
            },
        )
        rows = cursor.fetchall()
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["player_id"]), []).append(row)
        return {
            player_id: _aggregate_stats_context(items)
            for player_id, items in grouped.items()
        }

    def _load_social(self, player_ids: list[str]) -> dict[str, SocialSignalContext]:
        if not player_ids:
            return {}
        # Social signal storage is not implemented yet in this repo. Return empty
        # signal contexts so social strategies degrade to no-signal holds.
        return {player_id: SocialSignalContext() for player_id in player_ids}

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
    last_trade_price = None if row["last_trade_price"] is None else _decimal(row["last_trade_price"])
    unrealized_return_pct = None
    if last_trade_price is not None and last_trade_price > 0:
        unrealized_return_pct = float((current_price - last_trade_price) / last_trade_price)
    return BotPositionContext(
        instrument_id=UUID(str(row["instrument_id"])),
        player_id=None if row["player_id"] is None else UUID(str(row["player_id"])),
        club=None if row["club"] is None else str(row["club"]),
        quantity=quantity,
        current_price=current_price,
        market_value=market_value,
        last_trade_price=last_trade_price,
        unrealized_return_pct=unrealized_return_pct,
    )


def _aggregate_stats_context(rows: list[Mapping[str, Any]]) -> PlayerStatsContext:
    ratings = [_to_float(row["rating"]) for row in rows if row["rating"] is not None]
    minutes = [_stat_number(row["stats"], "minutes", "mins", "minutes_90s") for row in rows]
    minutes_values = [value for value in minutes if value is not None]
    goals = [_stat_number(row["stats"], "goals", "gls") or 0.0 for row in rows]
    assists = [_stat_number(row["stats"], "assists", "ast") or 0.0 for row in rows]
    clean_sheets = [
        _stat_number(row["stats"], "clean_sheets", "cs") or 0.0 for row in rows
    ]
    defensive = [
        (_stat_number(row["stats"], "tackles") or 0.0)
        + (_stat_number(row["stats"], "interceptions") or 0.0)
        + (_stat_number(row["stats"], "blocks") or 0.0)
        for row in rows
    ]
    shots = [
        _stat_number(row["stats"], "shots_total", "shots") or 0.0 for row in rows
    ]
    key_passes = [
        _stat_number(row["stats"], "key_passes", "passes_key") or 0.0 for row in rows
    ]
    cards = [
        (_stat_number(row["stats"], "cards_yellow", "yellow_cards") or 0.0)
        + 2.0 * (_stat_number(row["stats"], "cards_red", "red_cards") or 0.0)
        for row in rows
    ]

    row_count = len(rows)
    return PlayerStatsContext(
        observation_count=row_count,
        average_rating=(None if not ratings else fmean(ratings)),
        average_minutes=(None if not minutes_values else fmean(minutes_values)),
        goals_per_match=(0.0 if row_count == 0 else sum(goals) / row_count),
        assists_per_match=(0.0 if row_count == 0 else sum(assists) / row_count),
        clean_sheets_per_match=(
            0.0 if row_count == 0 else sum(clean_sheets) / row_count
        ),
        defensive_actions_per_match=(
            0.0 if row_count == 0 else sum(defensive) / row_count
        ),
        shots_per_match=(0.0 if row_count == 0 else sum(shots) / row_count),
        key_passes_per_match=(
            0.0 if row_count == 0 else sum(key_passes) / row_count
        ),
        cards_per_match=(0.0 if row_count == 0 else sum(cards) / row_count),
        latest_observed_at=rows[0]["observed_at"] if rows else None,
    )


def _stat_number(stats: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in stats:
            continue
        return _to_float(stats[key])
    return None


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


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
