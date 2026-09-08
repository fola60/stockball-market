from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from psycopg2.extras import Json

from app.database import connection as pooled_connection

from .matching import PlayerCandidate
from .models import MarketValueImportResult, MarketValueImportRow, MarketValueMatchStatus


class PostgresMarketValueRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_player_candidates(self) -> list[PlayerCandidate]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id::text,
                        display_name,
                        club,
                        metadata->>'date_of_birth',
                        metadata->>'nationality',
                        metadata
                    FROM players
                    """
                )
                rows = cursor.fetchall()

        return [
            PlayerCandidate(
                player_id=UUID(str(row[0])),
                display_name=str(row[1]),
                club=None if row[2] is None else str(row[2]),
                date_of_birth=_optional_date(row[3]),
                nationality=None if row[4] is None else str(row[4]),
                metadata=row[5] if isinstance(row[5], dict) else {},
            )
            for row in rows
        ]

    def list_provider_refs(self, source: str) -> dict[str, UUID]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT provider_player_id, player_id::text
                    FROM player_provider_refs
                    WHERE provider = %s
                    """,
                    (source,),
                )
                rows = cursor.fetchall()
        return {str(provider_player_id): UUID(str(player_id)) for provider_player_id, player_id in rows}

    def save_import(
        self,
        source: str,
        players_csv_path: str | None,
        valuations_csv_path: str,
        rows: list[MarketValueImportRow],
    ) -> MarketValueImportResult:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_value_import_batches (
                        source,
                        players_csv_path,
                        valuations_csv_path
                    ) VALUES (%s, %s, %s)
                    RETURNING id::text
                    """,
                    (source, players_csv_path, valuations_csv_path),
                )
                batch_id = UUID(str(cursor.fetchone()[0]))

                for row in rows:
                    market_value = row.market_value
                    match = row.match
                    cursor.execute(
                        """
                        INSERT INTO market_value_import_rows (
                            import_batch_id,
                            source,
                            source_player_id,
                            source_player_name,
                            source_club,
                            source_date_of_birth,
                            source_nationality,
                            value,
                            currency,
                            observed_at,
                            raw_payload,
                            matched_player_id,
                            match_status,
                            match_confidence,
                            match_reason
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            str(batch_id),
                            market_value.source,
                            market_value.source_player_id,
                            market_value.source_player_name,
                            market_value.source_club,
                            market_value.source_date_of_birth,
                            market_value.source_nationality,
                            market_value.value,
                            market_value.currency,
                            market_value.observed_at,
                            Json(dict(market_value.raw_payload)),
                            None if match.player_id is None else str(match.player_id),
                            match.status.value,
                            match.confidence,
                            match.reason,
                        ),
                    )

                    if match.status is MarketValueMatchStatus.MATCHED and match.player_id is not None:
                        self._upsert_provider_ref(cursor, row)
                        self._upsert_market_value_observation(cursor, row)

                counts = _count_rows(rows)
                cursor.execute(
                    """
                    UPDATE market_value_import_batches
                    SET
                        status = 'COMPLETED',
                        imported_rows = %s,
                        matched_rows = %s,
                        ambiguous_rows = %s,
                        unmatched_rows = %s,
                        rejected_rows = %s,
                        completed_at = now()
                    WHERE id = %s
                    """,
                    (
                        counts.imported_rows,
                        counts.matched_rows,
                        counts.ambiguous_rows,
                        counts.unmatched_rows,
                        counts.rejected_rows,
                        str(batch_id),
                    ),
                )
            connection.commit()

        return MarketValueImportResult(
            batch_id=batch_id,
            imported_rows=counts.imported_rows,
            matched_rows=counts.matched_rows,
            ambiguous_rows=counts.ambiguous_rows,
            unmatched_rows=counts.unmatched_rows,
            rejected_rows=counts.rejected_rows,
        )

    def _upsert_provider_ref(self, cursor: object, row: MarketValueImportRow) -> None:
        market_value = row.market_value
        match = row.match
        cursor.execute(
            """
            INSERT INTO player_provider_refs (
                player_id,
                provider,
                provider_player_id,
                provider_url,
                confidence,
                raw_identity,
                last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (provider, provider_player_id) DO UPDATE
            SET
                player_id = EXCLUDED.player_id,
                provider_url = EXCLUDED.provider_url,
                confidence = EXCLUDED.confidence,
                raw_identity = EXCLUDED.raw_identity,
                last_seen_at = now()
            """,
            (
                str(match.player_id),
                market_value.source,
                market_value.source_player_id,
                market_value.source_url,
                match.confidence,
                Json(
                    {
                        "source_player_name": market_value.source_player_name,
                        "source_club": market_value.source_club,
                        "source_date_of_birth": (
                            None
                            if market_value.source_date_of_birth is None
                            else market_value.source_date_of_birth.isoformat()
                        ),
                        "source_nationality": market_value.source_nationality,
                    }
                ),
            ),
        )

    def _upsert_market_value_observation(self, cursor: object, row: MarketValueImportRow) -> None:
        market_value = row.market_value
        match = row.match
        cursor.execute(
            """
            INSERT INTO player_market_value_observations (
                player_id,
                source,
                source_player_id,
                value,
                currency,
                observed_at,
                raw_payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (player_id, source, source_player_id, observed_at) DO UPDATE
            SET
                value = EXCLUDED.value,
                currency = EXCLUDED.currency,
                raw_payload = EXCLUDED.raw_payload,
                imported_at = now()
            """,
            (
                str(match.player_id),
                market_value.source,
                market_value.source_player_id,
                market_value.value,
                market_value.currency,
                market_value.observed_at,
                Json(dict(market_value.raw_payload)),
            ),
        )


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value)[:10])


@dataclass(frozen=True)
class ImportCounts:
    imported_rows: int
    matched_rows: int
    ambiguous_rows: int
    unmatched_rows: int
    rejected_rows: int


def _count_rows(rows: list[MarketValueImportRow]) -> ImportCounts:
    matched = sum(1 for row in rows if row.match.status is MarketValueMatchStatus.MATCHED)
    ambiguous = sum(1 for row in rows if row.match.status is MarketValueMatchStatus.AMBIGUOUS)
    unmatched = sum(1 for row in rows if row.match.status is MarketValueMatchStatus.UNMATCHED)
    rejected = sum(1 for row in rows if row.match.status is MarketValueMatchStatus.REJECTED)
    return ImportCounts(
        imported_rows=len(rows),
        matched_rows=matched,
        ambiguous_rows=ambiguous,
        unmatched_rows=unmatched,
        rejected_rows=rejected,
    )
