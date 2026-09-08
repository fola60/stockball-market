from __future__ import annotations

import os
from dataclasses import dataclass

DATABASE_URL_ENV = "STOCKBALL_WORKER_DATABASE_URL"
DATABASE_URL_FALLBACK_ENV = "DATABASE_URL"
REDIS_URL_ENV = "STOCKBALL_WORKER_REDIS_URL"
REDIS_URL_FALLBACK_ENV = "REDIS_URL"
TRADING_ENGINE_URL_ENV = "STOCKBALL_WORKER_TRADING_ENGINE_URL"
TRADING_ENGINE_URL_FALLBACK_ENV = "STOCKBALL_TRADING_ENGINE_URL"
API_URL_ENV = "STOCKBALL_WORKER_API_URL"
API_URL_FALLBACK_ENV = "STOCKBALL_API_URL"
QUEUE_NAME_ENV = "STOCKBALL_WORKER_QUEUE_NAME"
RETRY_QUEUE_NAME_ENV = "STOCKBALL_WORKER_RETRY_QUEUE_NAME"
SCHEDULE_CLAIM_PREFIX_ENV = "STOCKBALL_WORKER_SCHEDULE_CLAIM_PREFIX"
TRADING_ENGINE_TIMEOUT_ENV = "STOCKBALL_WORKER_TRADING_ENGINE_TIMEOUT_SECONDS"
FBREF_BASE_URL_ENV = "STOCKBALL_FBREF_BASE_URL"
FBREF_REQUEST_INTERVAL_ENV = "STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS"
FBREF_USER_AGENT_ENV = "STOCKBALL_FBREF_USER_AGENT"
FBREF_CACHE_TTL_SECONDS_ENV = "STOCKBALL_FBREF_CACHE_TTL_SECONDS"
BET365_SCHEDULE_ENABLED_ENV = "STOCKBALL_BET365_SCHEDULE_ENABLED"
BET365_LIVE_SCHEDULE_ENABLED_ENV = "STOCKBALL_BET365_LIVE_SCHEDULE_ENABLED"
BET365_LIVE_SCHEDULE_INTERVAL_MINUTES_ENV = (
    "STOCKBALL_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES"
)
BET365_LIVE_EVENT_WINDOW_MINUTES_ENV = "STOCKBALL_BET365_LIVE_EVENT_WINDOW_MINUTES"
BET365_WEBSITE_URL_ENV = "STOCKBALL_BET365_WEBSITE_URL"
BET365_WEBSITE_NAVIGATION_INTERVAL_ENV = (
    "STOCKBALL_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS"
)
BET365_COMPETITION_NAME_ENV = "STOCKBALL_BET365_COMPETITION_NAME"
BET365_MAX_MATCHES_ENV = "STOCKBALL_BET365_MAX_MATCHES"
BET365_PRE_MATCH_CUTOFF_MINUTES_ENV = "STOCKBALL_BET365_PRE_MATCH_CUTOFF_MINUTES"
BET365_BROWSER_ENABLED_ENV = "STOCKBALL_BET365_BROWSER_ENABLED"
BET365_BROWSER_IDLE_SECONDS_ENV = "STOCKBALL_BET365_BROWSER_IDLE_SECONDS"
BET365_JOB_TIMEOUT_SECONDS_ENV = "STOCKBALL_BET365_JOB_TIMEOUT_SECONDS"
SCHEDULED_REALTIME_MAX_LAG_SECONDS_ENV = (
    "STOCKBALL_SCHEDULED_REALTIME_MAX_LAG_SECONDS"
)
PLAYER_STATS_SCHEDULE_ENABLED_ENV = "STOCKBALL_PLAYER_STATS_SCHEDULE_ENABLED"
PLAYER_STATS_SCHEDULE_HOUR_UTC_ENV = "STOCKBALL_PLAYER_STATS_SCHEDULE_HOUR_UTC"
PLAYER_STATS_SCHEDULE_LEAGUE_ENV = "STOCKBALL_PLAYER_STATS_SCHEDULE_LEAGUE"
PLAYER_STATS_SCHEDULE_SEASON_ENV = "STOCKBALL_PLAYER_STATS_SCHEDULE_SEASON"
TWITTER_BEARER_TOKEN_ENV = "STOCKBALL_TWITTER_BEARER_TOKEN"
TWITTER_SEARCH_QUERY_ENV = "STOCKBALL_TWITTER_SEARCH_QUERY"
TWITTER_QUERY_KEY_ENV = "STOCKBALL_TWITTER_QUERY_KEY"
TWITTER_POLICY_ACKNOWLEDGED_ENV = "STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED"
TWITTER_REQUEST_INTERVAL_ENV = "STOCKBALL_TWITTER_REQUEST_INTERVAL_SECONDS"
TWITTER_MAX_RATE_LIMIT_SLEEP_ENV = "STOCKBALL_TWITTER_MAX_RATE_LIMIT_SLEEP_SECONDS"
TWITTER_MAX_RESULTS_ENV = "STOCKBALL_TWITTER_MAX_RESULTS"
TWITTER_MAX_PAGES_ENV = "STOCKBALL_TWITTER_MAX_PAGES_PER_POLL"
TWITTER_SCHEDULE_ENABLED_ENV = "STOCKBALL_TWITTER_INJURY_SCHEDULE_ENABLED"
TWITTER_SCHEDULE_INTERVAL_MINUTES_ENV = "STOCKBALL_TWITTER_INJURY_SCHEDULE_INTERVAL_MINUTES"
TWITTER_BROWSER_ENABLED_ENV = "STOCKBALL_TWITTER_BROWSER_ENABLED"
TWITTER_BROWSER_USER_DATA_DIR_ENV = "STOCKBALL_TWITTER_BROWSER_USER_DATA_DIR"
TWITTER_BROWSER_PROFILE_DIRECTORY_ENV = "STOCKBALL_TWITTER_BROWSER_PROFILE_DIRECTORY"
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
DEFAULT_API_URL = "http://api:8000"
DEFAULT_FBREF_BASE_URL = "https://fbref.com"
DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS = 7.5
DEFAULT_FBREF_USER_AGENT = (
    "StockballMarketWorker/0.1 "
    "(contact: engineering@stockball.local; provider=FBREF)"
)
DEFAULT_FBREF_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_BET365_WEBSITE_URL = "https://www.bet365.com/#/HO/"
DEFAULT_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS = 5.0
DEFAULT_BET365_COMPETITION_NAME = "Premier League"
DEFAULT_BET365_MAX_MATCHES = 20
DEFAULT_BET365_PRE_MATCH_CUTOFF_MINUTES = 5
DEFAULT_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES = 1
DEFAULT_BET365_LIVE_EVENT_WINDOW_MINUTES = 180
DEFAULT_BET365_BROWSER_IDLE_SECONDS = 0.3
DEFAULT_BET365_JOB_TIMEOUT_SECONDS = 10 * 60
DEFAULT_SCHEDULED_REALTIME_MAX_LAG_SECONDS = 2 * 60
DEFAULT_PLAYER_STATS_SCHEDULE_HOUR_UTC = 3
DEFAULT_PLAYER_STATS_SCHEDULE_LEAGUE = 9
DEFAULT_PLAYER_STATS_SCHEDULE_SEASON = 2025
DEFAULT_TWITTER_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_TWITTER_MAX_RATE_LIMIT_SLEEP_SECONDS = 60.0
DEFAULT_TWITTER_MAX_RESULTS = 100
DEFAULT_TWITTER_MAX_PAGES_PER_POLL = 10
DEFAULT_TWITTER_SCHEDULE_INTERVAL_MINUTES = 5
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
    api_url: str = DEFAULT_API_URL
    fbref_base_url: str = DEFAULT_FBREF_BASE_URL
    fbref_request_interval_seconds: float = DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS
    fbref_user_agent: str = DEFAULT_FBREF_USER_AGENT
    fbref_cache_ttl_seconds: int = DEFAULT_FBREF_CACHE_TTL_SECONDS
    bet365_schedule_enabled: bool = False
    bet365_live_schedule_enabled: bool = False
    bet365_live_schedule_interval_minutes: int = DEFAULT_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES
    bet365_live_event_window_minutes: int = DEFAULT_BET365_LIVE_EVENT_WINDOW_MINUTES
    bet365_website_url: str = DEFAULT_BET365_WEBSITE_URL
    bet365_website_navigation_interval_seconds: float = (
        DEFAULT_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS
    )
    bet365_competition_name: str = DEFAULT_BET365_COMPETITION_NAME
    bet365_max_matches: int = DEFAULT_BET365_MAX_MATCHES
    bet365_pre_match_cutoff_minutes: int = DEFAULT_BET365_PRE_MATCH_CUTOFF_MINUTES
    bet365_browser_enabled: bool = False
    bet365_browser_idle_seconds: float = DEFAULT_BET365_BROWSER_IDLE_SECONDS
    bet365_job_timeout_seconds: float = DEFAULT_BET365_JOB_TIMEOUT_SECONDS
    scheduled_realtime_max_lag_seconds: int = DEFAULT_SCHEDULED_REALTIME_MAX_LAG_SECONDS
    player_stats_schedule_enabled: bool = True
    player_stats_schedule_hour_utc: int = DEFAULT_PLAYER_STATS_SCHEDULE_HOUR_UTC
    player_stats_schedule_league: int = DEFAULT_PLAYER_STATS_SCHEDULE_LEAGUE
    player_stats_schedule_season: int = DEFAULT_PLAYER_STATS_SCHEDULE_SEASON
    twitter_bearer_token: str | None = None
    twitter_search_query: str | None = None
    twitter_query_key: str | None = None
    twitter_policy_acknowledged: bool = False
    twitter_request_interval_seconds: float = DEFAULT_TWITTER_REQUEST_INTERVAL_SECONDS
    twitter_max_rate_limit_sleep_seconds: float = DEFAULT_TWITTER_MAX_RATE_LIMIT_SLEEP_SECONDS
    twitter_max_results: int = DEFAULT_TWITTER_MAX_RESULTS
    twitter_max_pages_per_poll: int = DEFAULT_TWITTER_MAX_PAGES_PER_POLL
    twitter_injury_schedule_enabled: bool = False
    twitter_injury_schedule_interval_minutes: int = DEFAULT_TWITTER_SCHEDULE_INTERVAL_MINUTES
    twitter_browser_enabled: bool = False
    twitter_browser_user_data_dir: str | None = None
    twitter_browser_profile_directory: str | None = None
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
            api_url=os.getenv(API_URL_ENV)
            or os.getenv(API_URL_FALLBACK_ENV)
            or DEFAULT_API_URL,
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
            bet365_schedule_enabled=_bool_env(BET365_SCHEDULE_ENABLED_ENV, False),
            bet365_live_schedule_enabled=_bool_env(
                BET365_LIVE_SCHEDULE_ENABLED_ENV,
                False,
            ),
            bet365_live_schedule_interval_minutes=_int_env(
                BET365_LIVE_SCHEDULE_INTERVAL_MINUTES_ENV,
                DEFAULT_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES,
            ),
            bet365_live_event_window_minutes=_int_env(
                BET365_LIVE_EVENT_WINDOW_MINUTES_ENV,
                DEFAULT_BET365_LIVE_EVENT_WINDOW_MINUTES,
            ),
            bet365_website_url=os.getenv(BET365_WEBSITE_URL_ENV, DEFAULT_BET365_WEBSITE_URL),
            bet365_website_navigation_interval_seconds=_float_env(
                BET365_WEBSITE_NAVIGATION_INTERVAL_ENV,
                DEFAULT_BET365_WEBSITE_NAVIGATION_INTERVAL_SECONDS,
            ),
            bet365_competition_name=os.getenv(
                BET365_COMPETITION_NAME_ENV,
                DEFAULT_BET365_COMPETITION_NAME,
            ),
            bet365_max_matches=_int_env(BET365_MAX_MATCHES_ENV, DEFAULT_BET365_MAX_MATCHES),
            bet365_pre_match_cutoff_minutes=_int_env(
                BET365_PRE_MATCH_CUTOFF_MINUTES_ENV,
                DEFAULT_BET365_PRE_MATCH_CUTOFF_MINUTES,
            ),
            bet365_browser_enabled=_bool_env(BET365_BROWSER_ENABLED_ENV, False),
            bet365_browser_idle_seconds=_float_env(
                BET365_BROWSER_IDLE_SECONDS_ENV,
                DEFAULT_BET365_BROWSER_IDLE_SECONDS,
            ),
            bet365_job_timeout_seconds=_float_env(
                BET365_JOB_TIMEOUT_SECONDS_ENV,
                DEFAULT_BET365_JOB_TIMEOUT_SECONDS,
            ),
            scheduled_realtime_max_lag_seconds=_int_env(
                SCHEDULED_REALTIME_MAX_LAG_SECONDS_ENV,
                DEFAULT_SCHEDULED_REALTIME_MAX_LAG_SECONDS,
            ),
            player_stats_schedule_enabled=_bool_env(
                PLAYER_STATS_SCHEDULE_ENABLED_ENV,
                True,
            ),
            player_stats_schedule_hour_utc=_int_env(
                PLAYER_STATS_SCHEDULE_HOUR_UTC_ENV,
                DEFAULT_PLAYER_STATS_SCHEDULE_HOUR_UTC,
            ),
            player_stats_schedule_league=_int_env(
                PLAYER_STATS_SCHEDULE_LEAGUE_ENV,
                DEFAULT_PLAYER_STATS_SCHEDULE_LEAGUE,
            ),
            player_stats_schedule_season=_int_env(
                PLAYER_STATS_SCHEDULE_SEASON_ENV,
                DEFAULT_PLAYER_STATS_SCHEDULE_SEASON,
            ),
            twitter_bearer_token=os.getenv(TWITTER_BEARER_TOKEN_ENV),
            twitter_search_query=os.getenv(TWITTER_SEARCH_QUERY_ENV),
            twitter_query_key=os.getenv(TWITTER_QUERY_KEY_ENV),
            twitter_policy_acknowledged=_bool_env(TWITTER_POLICY_ACKNOWLEDGED_ENV, False),
            twitter_request_interval_seconds=_float_env(
                TWITTER_REQUEST_INTERVAL_ENV,
                DEFAULT_TWITTER_REQUEST_INTERVAL_SECONDS,
            ),
            twitter_max_rate_limit_sleep_seconds=_float_env(
                TWITTER_MAX_RATE_LIMIT_SLEEP_ENV,
                DEFAULT_TWITTER_MAX_RATE_LIMIT_SLEEP_SECONDS,
            ),
            twitter_max_results=_int_env(TWITTER_MAX_RESULTS_ENV, DEFAULT_TWITTER_MAX_RESULTS),
            twitter_max_pages_per_poll=_int_env(
                TWITTER_MAX_PAGES_ENV,
                DEFAULT_TWITTER_MAX_PAGES_PER_POLL,
            ),
            twitter_injury_schedule_enabled=_bool_env(TWITTER_SCHEDULE_ENABLED_ENV, False),
            twitter_browser_enabled=_bool_env(TWITTER_BROWSER_ENABLED_ENV, False),
            twitter_browser_user_data_dir=os.getenv(TWITTER_BROWSER_USER_DATA_DIR_ENV),
            twitter_browser_profile_directory=os.getenv(TWITTER_BROWSER_PROFILE_DIRECTORY_ENV),
            twitter_injury_schedule_interval_minutes=_int_env(
                TWITTER_SCHEDULE_INTERVAL_MINUTES_ENV,
                DEFAULT_TWITTER_SCHEDULE_INTERVAL_MINUTES,
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


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
