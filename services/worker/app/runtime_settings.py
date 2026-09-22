from __future__ import annotations

from typing import Any

from app.database import connection


class PostgresRuntimeSettings:
    """Reads the small allowlisted override set once per scheduler cycle."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def values(self) -> dict[str, Any]:
        with connection(self._database_url) as database, database.cursor() as cursor:
            cursor.execute("SELECT setting_key, value FROM runtime_settings")
            return {str(key): value for key, value in cursor.fetchall()}
