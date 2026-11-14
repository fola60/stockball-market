"""Backfills for history the forecasting features use but live ingestion only keeps the
latest of.

Match ratings are backfilled with the existing `ingest-fotmob-ratings --backfill`.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg2.extras import execute_values

from app.database import connection as pooled_connection


def backfill_market_value_history(
    database_url: str,
    valuations_csv_path: Path,
    *,
    source: str = "transfermarkt_csv",
    currency: str = "EUR",
) -> dict[str, Any]:
    """Store every dated value in a Transfermarkt `player_valuations.csv` for players the
    regular import has already matched.

    The regular import keeps each player's latest value. This adds the earlier ones, each
    dated by when it was published, so a forecast row can use the value that existed at its
    as-of date. Nothing reads history except the forecasting dataset: every other reader takes
    the latest observation, which this never changes. Rows already present are left alone.
    """
    with pooled_connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT source_player_id, player_id::text
                FROM player_market_value_observations
                WHERE source = %s
                """,
                (source,),
            )
            players = {str(source_id): str(player_id) for source_id, player_id in cursor.fetchall()}

    rows = []
    with valuations_csv_path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            player_id = players.get((record.get("player_id") or "").strip())
            value = (record.get("market_value_in_eur") or "").strip()
            observed_on = (record.get("date") or "").strip()[:10]
            if player_id is None or not value or not observed_on:
                continue
            try:
                amount = float(value)
                observed_at = datetime.fromisoformat(observed_on).replace(tzinfo=UTC)
            except ValueError:
                continue
            if amount <= 0:
                continue
            rows.append(
                (
                    player_id,
                    source,
                    record["player_id"].strip(),
                    amount,
                    currency,
                    observed_at,
                    json.dumps({"backfill": "market_value_history"}),
                )
            )

    inserted = 0
    if rows:
        with pooled_connection(database_url) as connection:
            with connection.cursor() as cursor:
                results = execute_values(
                    cursor,
                    """
                    INSERT INTO player_market_value_observations (
                        player_id, source, source_player_id, value, currency, observed_at,
                        raw_payload
                    )
                    VALUES %s
                    ON CONFLICT (player_id, source, source_player_id, observed_at) DO NOTHING
                    RETURNING 1
                    """,
                    rows,
                    template="(%s, %s, %s, %s, %s, %s, %s::jsonb)",
                    fetch=True,
                )
                inserted = len(results)
    return {"matched_players": len(players), "dated_values": len(rows), "inserted": inserted}
