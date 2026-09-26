from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

DATABASE_URL_ENV = "STOCKBALL_API_DATABASE_URL"
DATABASE_URL_FALLBACK_ENV = "DATABASE_URL"
TRADING_ENGINE_URL_ENV = "STOCKBALL_API_TRADING_ENGINE_URL"
TRADING_ENGINE_URL_FALLBACK_ENV = "STOCKBALL_TRADING_ENGINE_URL"
DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS = 5.0
REDIS_URL_ENV = "STOCKBALL_API_REDIS_URL"
DEV_PORTAL_ENABLED_ENV = "STOCKBALL_DEV_PORTAL_ENABLED"


@dataclass(frozen=True)
class Settings:
    database_url: str
    trading_engine_url: str
    trading_engine_timeout_seconds: float = DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS
    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "stockball:worker:jobs"
    trading_queue_name: str = "stockball:worker:trading"
    ingestion_queue_name: str = "stockball:worker:ingestion"
    dev_portal_enabled: bool = False
    user_opening_balance: Decimal = Decimal("100000.0000")

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
            redis_url=os.getenv(REDIS_URL_ENV, "redis://redis:6379/0"),
            queue_name=os.getenv("STOCKBALL_API_QUEUE_NAME", "stockball:worker:jobs"),
            trading_queue_name=os.getenv(
                "STOCKBALL_API_TRADING_QUEUE_NAME", "stockball:worker:trading"
            ),
            ingestion_queue_name=os.getenv(
                "STOCKBALL_API_INGESTION_QUEUE_NAME", "stockball:worker:ingestion"
            ),
            dev_portal_enabled=os.getenv(DEV_PORTAL_ENABLED_ENV, "false").lower()
            in {"1", "true", "yes", "on"},
            user_opening_balance=Decimal(
                os.getenv("STOCKBALL_USER_OPENING_BALANCE", "100000.0000")
            ),
        )
