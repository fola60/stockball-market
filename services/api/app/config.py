from __future__ import annotations

import os
from dataclasses import dataclass


DATABASE_URL_ENV = "STOCKBALL_API_DATABASE_URL"
DATABASE_URL_FALLBACK_ENV = "DATABASE_URL"


@dataclass(frozen=True)
class Settings:
    database_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv(DATABASE_URL_ENV) or os.getenv(DATABASE_URL_FALLBACK_ENV)
        if not database_url:
            raise RuntimeError(
                f"database url is required via {DATABASE_URL_ENV} or {DATABASE_URL_FALLBACK_ENV}"
            )
        return cls(database_url=database_url)
