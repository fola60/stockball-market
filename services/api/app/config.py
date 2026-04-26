from __future__ import annotations

import os
from dataclasses import dataclass


DATABASE_URL_ENV = "STOCKBALL_API_DATABASE_URL"
DATABASE_URL_FALLBACK_ENV = "DATABASE_URL"
TRADING_ENGINE_URL_ENV = "STOCKBALL_API_TRADING_ENGINE_URL"
TRADING_ENGINE_URL_FALLBACK_ENV = "STOCKBALL_TRADING_ENGINE_URL"
DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Settings:
    database_url: str
    trading_engine_url: str
    trading_engine_timeout_seconds: float = DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv(DATABASE_URL_ENV) or os.getenv(DATABASE_URL_FALLBACK_ENV)
        if not database_url:
            raise RuntimeError(
                f"database url is required via {DATABASE_URL_ENV} or {DATABASE_URL_FALLBACK_ENV}"
            )

        trading_engine_url = os.getenv(TRADING_ENGINE_URL_ENV) or os.getenv(
            TRADING_ENGINE_URL_FALLBACK_ENV
        )
        if not trading_engine_url:
            raise RuntimeError(
                "trading engine url is required via "
                f"{TRADING_ENGINE_URL_ENV} or {TRADING_ENGINE_URL_FALLBACK_ENV}"
            )

        return cls(
            database_url=database_url,
            trading_engine_url=trading_engine_url,
            trading_engine_timeout_seconds=DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS,
        )
