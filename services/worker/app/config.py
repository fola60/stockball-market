from __future__ import annotations

import os
from dataclasses import dataclass


DATABASE_URL_ENV = "STOCKBALL_WORKER_DATABASE_URL"
DATABASE_URL_FALLBACK_ENV = "DATABASE_URL"
REDIS_URL_ENV = "STOCKBALL_WORKER_REDIS_URL"
REDIS_URL_FALLBACK_ENV = "REDIS_URL"
TRADING_ENGINE_URL_ENV = "STOCKBALL_WORKER_TRADING_ENGINE_URL"
TRADING_ENGINE_URL_FALLBACK_ENV = "STOCKBALL_TRADING_ENGINE_URL"
QUEUE_NAME_ENV = "STOCKBALL_WORKER_QUEUE_NAME"
RETRY_QUEUE_NAME_ENV = "STOCKBALL_WORKER_RETRY_QUEUE_NAME"
SCHEDULE_CLAIM_PREFIX_ENV = "STOCKBALL_WORKER_SCHEDULE_CLAIM_PREFIX"
TRADING_ENGINE_TIMEOUT_ENV = "STOCKBALL_WORKER_TRADING_ENGINE_TIMEOUT_SECONDS"
FBREF_BASE_URL_ENV = "STOCKBALL_FBREF_BASE_URL"
FBREF_REQUEST_INTERVAL_ENV = "STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS"
FBREF_USER_AGENT_ENV = "STOCKBALL_FBREF_USER_AGENT"
FBREF_CACHE_TTL_SECONDS_ENV = "STOCKBALL_FBREF_CACHE_TTL_SECONDS"
SCHEDULER_POLL_SECONDS_ENV = "STOCKBALL_WORKER_SCHEDULER_POLL_SECONDS"
WORKER_BLOCK_SECONDS_ENV = "STOCKBALL_WORKER_BLOCK_SECONDS"
RETRY_DELAY_SECONDS_ENV = "STOCKBALL_WORKER_RETRY_DELAY_SECONDS"
MAX_ATTEMPTS_ENV = "STOCKBALL_WORKER_MAX_ATTEMPTS"
CLAIM_TTL_SECONDS_ENV = "STOCKBALL_WORKER_SCHEDULE_CLAIM_TTL_SECONDS"
LOG_LEVEL_ENV = "STOCKBALL_WORKER_LOG_LEVEL"

DEFAULT_QUEUE_NAME = "stockball:worker:jobs"
DEFAULT_RETRY_QUEUE_NAME = "stockball:worker:jobs:retry"
DEFAULT_SCHEDULE_CLAIM_PREFIX = "stockball:worker:schedule-claim"
DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS = 5.0
DEFAULT_FBREF_BASE_URL = "https://fbref.com"
DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS = 7.5
DEFAULT_FBREF_USER_AGENT = (
    "StockballMarketWorker/0.1 "
    "(contact: engineering@stockball.local; provider=FBREF)"
)
DEFAULT_FBREF_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_SCHEDULER_POLL_SECONDS = 60
DEFAULT_WORKER_BLOCK_SECONDS = 5
DEFAULT_RETRY_DELAY_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_SCHEDULE_CLAIM_TTL_SECONDS = 40 * 24 * 60 * 60
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    trading_engine_url: str
    fbref_base_url: str = DEFAULT_FBREF_BASE_URL
    fbref_request_interval_seconds: float = DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS
    fbref_user_agent: str = DEFAULT_FBREF_USER_AGENT
    fbref_cache_ttl_seconds: int = DEFAULT_FBREF_CACHE_TTL_SECONDS
    queue_name: str = DEFAULT_QUEUE_NAME
    retry_queue_name: str = DEFAULT_RETRY_QUEUE_NAME
    schedule_claim_prefix: str = DEFAULT_SCHEDULE_CLAIM_PREFIX
    trading_engine_timeout_seconds: float = DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS
    scheduler_poll_seconds: int = DEFAULT_SCHEDULER_POLL_SECONDS
    worker_block_seconds: int = DEFAULT_WORKER_BLOCK_SECONDS
    retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    schedule_claim_ttl_seconds: int = DEFAULT_SCHEDULE_CLAIM_TTL_SECONDS
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_required_env(DATABASE_URL_ENV, DATABASE_URL_FALLBACK_ENV),
            redis_url=_required_env(REDIS_URL_ENV, REDIS_URL_FALLBACK_ENV),
            trading_engine_url=_required_env(
                TRADING_ENGINE_URL_ENV,
                TRADING_ENGINE_URL_FALLBACK_ENV,
            ),
            fbref_base_url=os.getenv(FBREF_BASE_URL_ENV, DEFAULT_FBREF_BASE_URL),
            fbref_request_interval_seconds=_float_env(
                FBREF_REQUEST_INTERVAL_ENV,
                DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS,
            ),
            fbref_user_agent=os.getenv(FBREF_USER_AGENT_ENV, DEFAULT_FBREF_USER_AGENT),
            fbref_cache_ttl_seconds=_int_env(
                FBREF_CACHE_TTL_SECONDS_ENV,
                DEFAULT_FBREF_CACHE_TTL_SECONDS,
            ),
            queue_name=os.getenv(QUEUE_NAME_ENV, DEFAULT_QUEUE_NAME),
            retry_queue_name=os.getenv(RETRY_QUEUE_NAME_ENV, DEFAULT_RETRY_QUEUE_NAME),
            schedule_claim_prefix=os.getenv(
                SCHEDULE_CLAIM_PREFIX_ENV,
                DEFAULT_SCHEDULE_CLAIM_PREFIX,
            ),
            trading_engine_timeout_seconds=_float_env(
                TRADING_ENGINE_TIMEOUT_ENV,
                DEFAULT_TRADING_ENGINE_TIMEOUT_SECONDS,
            ),
            scheduler_poll_seconds=_int_env(
                SCHEDULER_POLL_SECONDS_ENV,
                DEFAULT_SCHEDULER_POLL_SECONDS,
            ),
            worker_block_seconds=_int_env(
                WORKER_BLOCK_SECONDS_ENV,
                DEFAULT_WORKER_BLOCK_SECONDS,
            ),
            retry_delay_seconds=_int_env(
                RETRY_DELAY_SECONDS_ENV,
                DEFAULT_RETRY_DELAY_SECONDS,
            ),
            max_attempts=_int_env(MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS),
            schedule_claim_ttl_seconds=_int_env(
                CLAIM_TTL_SECONDS_ENV,
                DEFAULT_SCHEDULE_CLAIM_TTL_SECONDS,
            ),
            log_level=os.getenv(LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL).upper(),
        )


@dataclass(frozen=True)
class FbrefIngestionSettings:
    database_url: str
    base_url: str = DEFAULT_FBREF_BASE_URL
    request_interval_seconds: float = DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS
    user_agent: str = DEFAULT_FBREF_USER_AGENT
    cache_ttl_seconds: int = DEFAULT_FBREF_CACHE_TTL_SECONDS

    @classmethod
    def from_env(cls) -> "FbrefIngestionSettings":
        return cls(
            database_url=_required_env(DATABASE_URL_ENV, DATABASE_URL_FALLBACK_ENV),
            base_url=os.getenv(FBREF_BASE_URL_ENV, DEFAULT_FBREF_BASE_URL),
            request_interval_seconds=_float_env(
                FBREF_REQUEST_INTERVAL_ENV,
                DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS,
            ),
            user_agent=os.getenv(FBREF_USER_AGENT_ENV, DEFAULT_FBREF_USER_AGENT),
            cache_ttl_seconds=_int_env(
                FBREF_CACHE_TTL_SECONDS_ENV,
                DEFAULT_FBREF_CACHE_TTL_SECONDS,
            ),
        )


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: str

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(database_url=_required_env(DATABASE_URL_ENV, DATABASE_URL_FALLBACK_ENV))


def _required_env(primary: str, fallback: str) -> str:
    value = os.getenv(primary) or os.getenv(fallback)
    if value:
        return value
    raise RuntimeError(f"required environment variable missing: {primary} or {fallback}")


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return int(raw_value)


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return float(raw_value)
