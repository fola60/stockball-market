from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.database import connection as pooled_connection
from app.traders.models import (
    LeaderboardFilter,
    LeaderboardPage,
    TraderHoldingRecord,
    TraderKind,
    TraderProfileRecord,
    TraderStandingRecord,
    TraderTradeRecord,
)

# Every ranked account with its net worth: cash plus holdings at current prices. Ranks are
# computed across all public traders so a person's rank doesn't change with the filter.
# Admin and system accounts (such as the player-share reserve) are never ranked.
_STANDINGS = """
    WITH holdings AS (
        SELECT
            position.portfolio_id,
            SUM(position.quantity * instrument.current_price) AS holdings_value,
            COUNT(*) AS holdings_count
        FROM positions AS position
        JOIN instruments AS instrument ON instrument.id = position.instrument_id
        WHERE position.quantity > 0
        GROUP BY position.portfolio_id
    ),
    standings AS (
        SELECT
            account.id AS account_id,
            account.display_name,
            account.account_type,
            account.created_at AS joined_at,
            portfolio.cash_balance,
            COALESCE(holdings.holdings_value, 0) AS holdings_value,
            COALESCE(holdings.holdings_count, 0) AS holdings_count,
            portfolio.cash_balance + COALESCE(holdings.holdings_value, 0) AS net_worth
        FROM accounts AS account
        JOIN portfolios AS portfolio ON portfolio.account_id = account.id
        LEFT JOIN holdings ON holdings.portfolio_id = portfolio.id
        WHERE account.status = 'ACTIVE'
          AND account.account_type IN ('USER', 'SYNTHETIC_TRADER')
    ),
    ranked AS (
        SELECT
            standings.*,
            RANK() OVER (ORDER BY net_worth DESC) AS rank
        FROM standings
    )
"""

_ACCOUNT_TYPES = {
    LeaderboardFilter.ALL: ["USER", "SYNTHETIC_TRADER"],
    LeaderboardFilter.PEOPLE: ["USER"],
    LeaderboardFilter.BOTS: ["SYNTHETIC_TRADER"],
}


class TradersRepository(Protocol):
    def leaderboard(
        self, filter_: LeaderboardFilter, limit: int, offset: int
    ) -> LeaderboardPage: ...

    def profile(self, account_id: UUID, trade_limit: int) -> TraderProfileRecord | None: ...


class PostgresTradersRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[RealDictCursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def leaderboard(
        self, filter_: LeaderboardFilter, limit: int, offset: int
    ) -> LeaderboardPage:
        params = {"types": _ACCOUNT_TYPES[filter_], "limit": limit, "offset": offset}
        with self._cursor() as cursor:
            cursor.execute(
                _STANDINGS
                + """
                SELECT *, COUNT(*) OVER () AS total
                FROM ranked
                WHERE account_type = ANY(%(types)s)
                ORDER BY rank, display_name, account_id
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                params,
            )
            rows = cursor.fetchall()
            if rows:
                total = int(rows[0]["total"])
            else:
                cursor.execute(
                    _STANDINGS + "SELECT COUNT(*) AS total FROM ranked WHERE account_type = ANY(%(types)s)",
                    params,
                )
                count_row = cursor.fetchone()
                total = int(count_row["total"]) if count_row else 0
        return LeaderboardPage(
            entries=[_standing(row) for row in rows], total=total, limit=limit, offset=offset
        )

    def profile(self, account_id: UUID, trade_limit: int) -> TraderProfileRecord | None:
        with self._cursor() as cursor:
            cursor.execute(
                _STANDINGS + "SELECT * FROM ranked WHERE account_id = %(account_id)s",
                {"account_id": str(account_id)},
            )
            standing_row = cursor.fetchone()
            if standing_row is None:
                return None
            cursor.execute(
                """
                SELECT
                    instrument.id AS instrument_id,
                    instrument.symbol,
                    player.display_name AS player_name,
                    player.club AS player_club,
                    player.position AS player_position,
                    position.quantity,
                    instrument.current_price,
                    position.quantity * instrument.current_price AS market_value,
                    COALESCE(
                        ROUND(
                            ((instrument.current_price - opening.opening_price)
                                / NULLIF(opening.opening_price, 0)) * 100,
                            4
                        ),
                        0
                    ) AS price_change_24h
                FROM positions AS position
                JOIN portfolios AS portfolio ON portfolio.id = position.portfolio_id
                JOIN instruments AS instrument ON instrument.id = position.instrument_id
                JOIN players AS player ON player.id = instrument.player_id
                LEFT JOIN LATERAL (
                    SELECT snapshot.old_price AS opening_price
                    FROM price_snapshots AS snapshot
                    WHERE snapshot.instrument_id = instrument.id
                      AND snapshot.captured_at >= now() - interval '24 hours'
                    ORDER BY snapshot.captured_at ASC, snapshot.id ASC
                    LIMIT 1
                ) AS opening ON TRUE
                WHERE portfolio.account_id = %(account_id)s
                  AND position.quantity > 0
                ORDER BY market_value DESC, player.display_name
                """,
                {"account_id": str(account_id)},
            )
            holding_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT
                    trade.id AS trade_id,
                    trade.instrument_id,
                    player.display_name AS player_name,
                    trade.side,
                    trade.shares,
                    trade.execution_price,
                    trade.gross_amount,
                    trade.executed_at
                FROM trades AS trade
                JOIN instruments AS instrument ON instrument.id = trade.instrument_id
                JOIN players AS player ON player.id = instrument.player_id
                WHERE trade.account_id = %(account_id)s
                ORDER BY trade.executed_at DESC, trade.id DESC
                LIMIT %(limit)s
                """,
                {"account_id": str(account_id), "limit": trade_limit},
            )
            trade_rows = cursor.fetchall()
        return TraderProfileRecord(
            standing=_standing(standing_row),
            holdings=[_holding(row) for row in holding_rows],
            recent_trades=[_trade(row) for row in trade_rows],
        )


def _standing(row: dict) -> TraderStandingRecord:
    return TraderStandingRecord(
        account_id=UUID(str(row["account_id"])),
        display_name=row["display_name"],
        kind=TraderKind.BOT if row["account_type"] == "SYNTHETIC_TRADER" else TraderKind.PERSON,
        rank=int(row["rank"]),
        net_worth=_money(row["net_worth"]),
        cash_balance=_money(row["cash_balance"]),
        holdings_value=_money(row["holdings_value"]),
        holdings_count=int(row["holdings_count"]),
        joined_at=row["joined_at"],
    )


def _holding(row: dict) -> TraderHoldingRecord:
    return TraderHoldingRecord(
        instrument_id=UUID(str(row["instrument_id"])),
        symbol=row["symbol"],
        player_name=row["player_name"],
        player_club=row["player_club"],
        player_position=row["player_position"],
        quantity=format_decimal(Decimal(row["quantity"]).normalize()),
        current_price=_money(row["current_price"]),
        market_value=_money(row["market_value"]),
        price_change_24h=format_decimal(Decimal(row["price_change_24h"])),
    )


def _trade(row: dict) -> TraderTradeRecord:
    return TraderTradeRecord(
        trade_id=UUID(str(row["trade_id"])),
        instrument_id=UUID(str(row["instrument_id"])),
        player_name=row["player_name"],
        side=row["side"],
        shares=format_decimal(Decimal(row["shares"]).normalize()),
        execution_price=_money(row["execution_price"]),
        gross_amount=_money(row["gross_amount"]),
        executed_at=row["executed_at"],
    )


def _money(value: Decimal) -> str:
    return format_decimal(Decimal(value).quantize(Decimal("0.0001")))
