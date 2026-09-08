from __future__ import annotations

from datetime import UTC

from app.database import connection as pooled_connection

from .models import FBREF_PROVIDER, FbrefRawPage


class PostgresFbrefRawPageRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_latest_successful_page(self, source_url: str) -> FbrefRawPage | None:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        provider,
                        source_url,
                        content_hash,
                        body,
                        status_code,
                        content_type,
                        fetched_at
                    FROM provider_raw_documents
                    WHERE provider = %s
                      AND source_url = %s
                      AND status_code >= 200
                      AND status_code < 300
                    ORDER BY fetched_at DESC
                    LIMIT 1
                    """,
                    (FBREF_PROVIDER, source_url),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        fetched_at = row[6]
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return FbrefRawPage(
            provider=str(row[0]),
            source_url=str(row[1]),
            content_hash=str(row[2]),
            body=str(row[3]),
            status_code=int(row[4]),
            content_type=None if row[5] is None else str(row[5]),
            fetched_at=fetched_at,
        )

    def save_page(self, page: FbrefRawPage) -> None:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO provider_raw_documents (
                        provider,
                        source_url,
                        content_hash,
                        body,
                        status_code,
                        content_type,
                        fetched_at,
                        last_seen_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, now()
                    )
                    ON CONFLICT (provider, source_url, content_hash) DO UPDATE
                    SET
                        status_code = EXCLUDED.status_code,
                        content_type = EXCLUDED.content_type,
                        fetched_at = EXCLUDED.fetched_at,
                        last_seen_at = now()
                    """,
                    (
                        page.provider,
                        page.source_url,
                        page.content_hash,
                        page.body,
                        page.status_code,
                        page.content_type,
                        page.fetched_at,
                    ),
                )
            connection.commit()
