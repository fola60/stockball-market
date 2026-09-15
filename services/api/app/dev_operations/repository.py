from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Iterator, Mapping
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection


class PostgresDevOperationsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def create_run(
        self, run_id: UUID, operation_type: str, job_type: str, parameters: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO job_runs (
                    id, operation_type, job_type, source, status, parameters
                )
                VALUES (
                    %(id)s, %(operation_type)s, %(job_type)s, 'MANUAL',
                    'QUEUED', %(parameters)s::jsonb
                )
                RETURNING *
                """,
                {
                    "id": str(run_id),
                    "operation_type": operation_type,
                    "job_type": job_type,
                    "parameters": json.dumps(dict(parameters)),
                },
            )
            return _serialize_required(cursor.fetchone(), "job run insert")

    def mark_enqueue_failed(self, run_id: UUID, message: str) -> None:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE job_runs
                SET status = 'FAILED', error_message = %(message)s,
                    completed_at = now(), updated_at = now()
                WHERE id = %(id)s
                """,
                {"id": str(run_id), "message": message[:2000]},
            )

    def list_runs(
        self,
        limit: int = 100,
        *,
        operation_type: str | None = None,
        exclude_operation_type: list[str] | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM job_runs
                WHERE (%(operation_type)s IS NULL OR operation_type = %(operation_type)s)
                  AND (%(exclude_operation_type)s IS NULL OR NOT operation_type = ANY(%(exclude_operation_type)s))
                  AND (%(status)s IS NULL OR status = %(status)s)
                  AND (%(source)s IS NULL OR source = %(source)s)
                ORDER BY enqueued_at DESC
                LIMIT %(limit)s
                """,
                {
                    "limit": limit,
                    "operation_type": operation_type,
                    "exclude_operation_type": exclude_operation_type,
                    "status": status,
                    "source": source,
                },
            )
            return [_serialize(row) for row in cursor.fetchall()]

    def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM job_runs WHERE id = %(id)s", {"id": str(run_id)})
            row = cursor.fetchone()
            return None if row is None else _serialize(row)

    def summary(self) -> dict[str, Any]:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE enqueued_at >= now() - interval '24 hours') AS total_24h,
                    COUNT(*) FILTER (WHERE status = 'SUCCEEDED' AND enqueued_at >= now() - interval '24 hours') AS succeeded_24h,
                    COUNT(*) FILTER (WHERE status = 'FAILED' AND enqueued_at >= now() - interval '24 hours') AS failed_24h,
                    COALESCE(SUM(successful_items) FILTER (WHERE enqueued_at >= now() - interval '24 hours'), 0) AS successful_items_24h,
                    COALESCE(SUM(failed_items) FILTER (WHERE enqueued_at >= now() - interval '24 hours'), 0) AS failed_items_24h
                FROM job_runs
                """
            )
            run_stats = dict(_required_row(cursor.fetchone(), "job run summary"))
            cursor.execute(
                """
                SELECT b.status, COUNT(*) AS count
                FROM synthetic_trader_bots b
                JOIN synthetic_trader_bot_configs c ON c.id = b.config_id
                WHERE c.strategy_engine <> 'SOCIAL_SENTIMENT'
                GROUP BY b.status
                ORDER BY b.status
                """
            )
            bot_statuses = {row["status"]: int(row["count"]) for row in cursor.fetchall()}
        return {**{key: int(value) for key, value in run_stats.items()}, "bot_statuses": bot_statuses}

    def social_ingestion_summary(self) -> dict[str, Any]:
        with self._connection() as connection, connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            cursor.execute(
                """
                SELECT source.provider, COUNT(DISTINCT source.id) AS source_count,
                       COUNT(DISTINCT subscription.id) FILTER (
                           WHERE subscription.enabled
                       ) AS subscription_count,
                       COUNT(DISTINCT subscription.id) FILTER (
                           WHERE subscription.enabled
                             AND COALESCE(
                                 ingestion_cursor.next_eligible_poll_at,
                                 subscription.next_eligible_poll_at,
                                 '-infinity'::timestamptz
                             ) <= now()
                       ) AS due_count
                FROM social_sources source
                LEFT JOIN social_subscriptions subscription
                  ON subscription.source_id = source.id
                LEFT JOIN social_ingestion_cursors ingestion_cursor
                  ON ingestion_cursor.subscription_id = subscription.id
                WHERE source.enabled AND source.policy_status = 'APPROVED'
                GROUP BY source.provider
                ORDER BY source.provider
                """
            )
            provider_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT COUNT(*) AS documents,
                       COUNT(observation.id) AS classified,
                       COUNT(observation.id) FILTER (
                           WHERE observation.entity_type = 'UNKNOWN'
                       ) AS unresolved,
                       MAX(document.ingested_at) AS latest_document_at
                FROM social_documents document
                LEFT JOIN social_observations observation
                  ON observation.document_id = document.id
                WHERE document.deleted_at IS NULL
                """
            )
            document_row = _required_row(cursor.fetchone(), "social document summary")
            cursor.execute(
                """
                SELECT observation.sentiment, COUNT(*) AS count
                FROM social_observations observation
                JOIN social_documents document ON document.id = observation.document_id
                WHERE document.deleted_at IS NULL
                GROUP BY observation.sentiment
                ORDER BY observation.sentiment
                """
            )
            sentiments = {
                str(row["sentiment"]): int(row["count"]) for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT enrichment.status, COUNT(*) AS count
                FROM social_document_enrichments enrichment
                GROUP BY enrichment.status
                ORDER BY enrichment.status
                """
            )
            enrichments = {
                str(row["status"]): int(row["count"]) for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT MAX(last_success_at) AS latest_success_at
                FROM social_ingestion_cursors
                """
            )
            cursor_row = _required_row(cursor.fetchone(), "social cursor summary")
        providers = {
            str(row["provider"]): {
                "sources": int(row["source_count"]),
                "subscriptions": int(row["subscription_count"]),
                "due": int(row["due_count"]),
            }
            for row in provider_rows
        }
        return {
            "providers": providers,
            "enabled_sources": sum(value["sources"] for value in providers.values()),
            "enabled_subscriptions": sum(
                value["subscriptions"] for value in providers.values()
            ),
            "due_subscriptions": sum(value["due"] for value in providers.values()),
            "documents": int(document_row["documents"]),
            "classified": int(document_row["classified"]),
            "unresolved": int(document_row["unresolved"]),
            "latest_document_at": _isoformat(document_row["latest_document_at"]),
            "latest_success_at": _isoformat(cursor_row["latest_success_at"]),
            "sentiments": sentiments,
            "enrichments": enrichments,
        }

    def executable_run_ids(self, run_ids: list[str]) -> set[str]:
        if not run_ids:
            return set()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM job_runs
                WHERE id = ANY(%(run_ids)s::uuid[])
                  AND status IN ('QUEUED', 'RETRYING')
                """,
                {"run_ids": run_ids},
            )
            return {str(row[0]) for row in cursor.fetchall()}

    def list_bots(self) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT b.id, b.bot_key, b.display_name, b.status, b.last_ticked_at,
                       b.next_tick_after, c.config_key, c.strategy_engine,
                       p.cash_balance,
                       COUNT(pos.instrument_id) FILTER (WHERE pos.quantity > 0) AS position_count
                FROM synthetic_trader_bots b
                JOIN synthetic_trader_bot_configs c ON c.id = b.config_id
                JOIN portfolios p ON p.account_id = b.account_id
                LEFT JOIN positions pos ON pos.portfolio_id = p.id
                WHERE c.strategy_engine <> 'SOCIAL_SENTIMENT'
                GROUP BY b.id, c.config_key, c.strategy_engine, p.cash_balance
                ORDER BY b.created_at DESC
                """
            )
            return [_serialize(row) for row in cursor.fetchall()]

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT config_key, strategy_engine, display_name, enabled, config
                FROM synthetic_trader_bot_configs
                WHERE strategy_engine <> 'SOCIAL_SENTIMENT'
                ORDER BY config_key
                """
            )
            return [_serialize(row) for row in cursor.fetchall()]

    def get_bot_details(self, bot_id: UUID) -> dict[str, Any] | None:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT b.id, b.account_id, p.id AS portfolio_id, b.bot_key,
                       b.display_name, b.status, b.config_overrides,
                       b.last_ticked_at, b.next_tick_after, b.created_at, b.updated_at,
                       a.handle, p.cash_balance, c.config_key, c.display_name AS profile_name,
                       c.strategy_engine, c.version AS config_version, c.config
                FROM synthetic_trader_bots b
                JOIN accounts a ON a.id = b.account_id
                JOIN portfolios p ON p.account_id = b.account_id
                JOIN synthetic_trader_bot_configs c ON c.id = b.config_id
                WHERE b.id = %(bot_id)s
                  AND c.strategy_engine <> 'SOCIAL_SENTIMENT'
                """,
                {"bot_id": str(bot_id)},
            )
            bot = cursor.fetchone()
            if bot is None:
                return None

            cursor.execute(
                """
                SELECT pos.instrument_id, i.symbol, i.display_name, player.club,
                       pos.quantity, i.current_price,
                       pos.quantity * i.current_price AS market_value,
                       pos.updated_at,
                       latest.execution_price AS last_trade_price,
                       latest.executed_at AS last_trade_at
                FROM positions pos
                JOIN instruments i ON i.id = pos.instrument_id
                LEFT JOIN players player ON player.id = i.player_id
                LEFT JOIN LATERAL (
                    SELECT execution_price, executed_at
                    FROM trades
                    WHERE portfolio_id = %(portfolio_id)s
                      AND instrument_id = pos.instrument_id
                    ORDER BY executed_at DESC, id DESC
                    LIMIT 1
                ) latest ON true
                WHERE pos.portfolio_id = %(portfolio_id)s AND pos.quantity > 0
                ORDER BY market_value DESC, i.symbol
                """,
                {"portfolio_id": str(bot["portfolio_id"])},
            )
            positions = [_serialize(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT t.id, t.instrument_id, i.symbol, t.side, t.shares,
                       t.execution_price, t.gross_amount, t.executed_at
                FROM trades t
                JOIN instruments i ON i.id = t.instrument_id
                WHERE t.account_id = %(account_id)s
                ORDER BY t.executed_at DESC, t.id DESC
                LIMIT 20
                """,
                {"account_id": str(bot["account_id"])},
            )
            recent_trades = [_serialize(row) for row in cursor.fetchall()]

            cursor.execute(
                """
                SELECT COUNT(*) AS trades_today,
                       COALESCE(SUM(gross_amount), 0) AS turnover_today,
                       MAX(executed_at) AS last_trade_at
                FROM trades
                WHERE account_id = %(account_id)s
                  AND executed_at >= date_trunc('day', now())
                """,
                {"account_id": str(bot["account_id"])},
            )
            activity = _serialize_required(cursor.fetchone(), "bot activity summary")

        serialized_bot = _serialize(bot)
        total_position_value = sum(
            (Decimal(str(position["market_value"])) for position in positions), Decimal("0")
        )
        return {
            **serialized_bot,
            "positions": positions,
            "recent_trades": recent_trades,
            "activity": activity,
            "position_count": len(positions),
            "position_value": str(total_position_value),
            "total_equity": str(Decimal(str(serialized_bot["cash_balance"])) + total_position_value),
        }

    def list_trades(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        account_type: str | None = None,
        side: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "limit": limit,
            "offset": offset,
            "account_type": account_type,
            "side": side,
        }
        where_clause = """
            WHERE (%(account_type)s::text IS NULL OR a.account_type = %(account_type)s)
              AND (%(side)s::text IS NULL OR t.side = %(side)s)
        """
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE t.side = 'BUY') AS buys,
                       COUNT(*) FILTER (WHERE t.side = 'SELL') AS sells,
                       COUNT(*) FILTER (WHERE a.account_type = 'USER') AS user_trades,
                       COUNT(*) FILTER (WHERE a.account_type = 'SYNTHETIC_TRADER') AS synthetic_trades,
                       COALESCE(SUM(t.gross_amount), 0) AS gross_amount
                FROM trades t
                JOIN accounts a ON a.id = t.account_id
                {where_clause}
                """,
                params,
            )
            summary = _serialize_required(cursor.fetchone(), "trade summary")
            cursor.execute(
                f"""
                SELECT t.id, t.order_id, t.account_id, t.portfolio_id, t.instrument_id,
                       t.side, t.shares, t.execution_price, t.gross_amount, t.executed_at,
                       i.symbol, i.display_name AS instrument_name,
                       player.display_name AS player_name, player.club,
                       a.handle, a.display_name AS account_name, a.account_type,
                       COALESCE(b.display_name, a.display_name) AS actor_name,
                       b.id AS bot_id, b.bot_key, b.display_name AS bot_name,
                       c.strategy_engine
                FROM trades t
                JOIN accounts a ON a.id = t.account_id
                JOIN instruments i ON i.id = t.instrument_id
                LEFT JOIN players player ON player.id = i.player_id
                LEFT JOIN synthetic_trader_bots b ON b.account_id = a.id
                LEFT JOIN synthetic_trader_bot_configs c ON c.id = b.config_id
                {where_clause}
                ORDER BY t.executed_at DESC, t.id DESC
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                params,
            )
            items = [_serialize(row) for row in cursor.fetchall()]
        return {
            "items": items,
            "total": int(summary["total"]),
            "limit": limit,
            "offset": offset,
            "summary": summary,
        }

    def get_trade_details(self, trade_id: UUID) -> dict[str, Any] | None:
        with self._connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT t.id, t.order_id, t.account_id, t.portfolio_id, t.instrument_id,
                       t.side, t.shares, t.execution_price, t.gross_amount,
                       t.executed_at, t.created_at,
                       o.request_id, o.status AS order_status, o.submitted_at,
                       o.filled_at, o.rejection_reason,
                       a.handle, a.email, a.display_name AS account_name,
                       a.account_type, a.status AS account_status,
                       COALESCE(b.display_name, a.display_name) AS actor_name,
                       p.cash_balance AS current_cash_balance,
                       pos.quantity AS current_position_quantity,
                       i.symbol, i.display_name AS instrument_name, i.instrument_type,
                       i.current_price, i.trading_status,
                       player.id AS player_id, player.display_name AS player_name,
                       player.club, player.position AS player_position,
                       b.id AS bot_id, b.bot_key, b.display_name AS bot_name,
                       b.status AS bot_status, b.last_ticked_at, b.next_tick_after,
                       c.config_key, c.display_name AS profile_name,
                       c.strategy_engine, c.version AS config_version,
                       snapshot.old_price, snapshot.new_price,
                       snapshot.reason AS price_change_reason,
                       ledger.reason AS cash_ledger_reason,
                       ledger.amount_delta AS cash_amount_delta,
                       ledger.balance_after AS cash_balance_after
                FROM trades t
                JOIN orders o ON o.id = t.order_id
                JOIN accounts a ON a.id = t.account_id
                JOIN portfolios p ON p.id = t.portfolio_id
                JOIN instruments i ON i.id = t.instrument_id
                LEFT JOIN players player ON player.id = i.player_id
                LEFT JOIN positions pos
                    ON pos.portfolio_id = t.portfolio_id
                   AND pos.instrument_id = t.instrument_id
                LEFT JOIN synthetic_trader_bots b ON b.account_id = a.id
                LEFT JOIN synthetic_trader_bot_configs c ON c.id = b.config_id
                LEFT JOIN price_snapshots snapshot ON snapshot.trade_id = t.id
                LEFT JOIN cash_ledger_entries ledger ON ledger.trade_id = t.id
                WHERE t.id = %(trade_id)s
                """,
                {"trade_id": str(trade_id)},
            )
            row = cursor.fetchone()
            return None if row is None else _serialize(row)


def _serialize(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (datetime,)):
            result[key] = value.astimezone(UTC).isoformat()
        elif isinstance(value, UUID):
            result[key] = str(value)
        elif hasattr(value, "as_tuple"):
            result[key] = str(value)
        else:
            result[key] = value
    return result


def _isoformat(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise TypeError("expected a datetime value")
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()


def _required_row(row: Mapping[str, Any] | None, query: str) -> Mapping[str, Any]:
    if row is None:
        raise RuntimeError(f"{query} returned no row")
    return row


def _serialize_required(row: Mapping[str, Any] | None, query: str) -> dict[str, Any]:
    return _serialize(_required_row(row, query))
