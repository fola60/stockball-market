"""Wiring for the long-running worker processes.

- The scheduler enqueues recurring jobs onto the trading and ingestion queues.
- The job worker consumes one queue. Deployments run it twice, once per queue, so slow
  ingestion jobs never delay synthetic trading ticks or top-ups.
"""

from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.ingestion.social import PostgresSocialRepository
from app.jobs import (
    AggregateSocialSignalsJobHandler,
    CheckMarketFreezesJobHandler,
    FunctionJobHandler,
    IngestBet365OddsJobHandler,
    IngestFixturesJobHandler,
    IngestPlayersJobHandler,
    IngestPlayerStatsJobHandler,
    IngestSocialFeedsJobHandler,
    IngestTwitterInjuriesJobHandler,
    JobType,
    ProcessSocialDocumentsJobHandler,
    SyntheticTraderTickJobHandler,
    TopupJobHandler,
    WorkerJobRunner,
    WorkerProcess,
)
from app.jobs.admin_handlers import (
    bootstrap_portfolios_handler,
    market_value_import_handler,
    seed_player_shares_handler,
    set_bot_status_handler,
    spawn_traders_handler,
)
from app.operation_runs import PostgresOperationRunReporter, PostgresScheduledRunRepository
from app.process_state import RedisProcessState
from app.queue import JobRoutingQueue, RedisJobQueue, RedisRetryQueue, RedisScheduleClaimStore
from app.runtime_settings import PostgresRuntimeSettings
from app.scheduler import DueSocialSubscriptionDispatcher, SchedulerProcess, SchedulerService
from app.scheduler.models import default_scheduler_plans
from app.seeding import (
    PostgresSyntheticPortfolioBootstrapRepository,
    SyntheticPortfolioBootstrapService,
)
from app.synthetic_traders import PostgresSyntheticTraderRepository
from app.topups import PostgresTopupRepository, TopupService

from .factories import (
    build_bet365_ingestion_service,
    build_fixture_ingestion_service,
    build_market_value_import_service,
    build_match_freeze_service,
    build_player_seed_service,
    build_player_stats_ingestion_service,
    build_social_source_handler,
    build_synthetic_trader_service,
    build_synthetic_trader_spawner,
    build_twitter_injury_ingestion_service,
    fbref_settings,
    trading_engine_client,
)


def build_scheduler_process(settings: Settings) -> SchedulerProcess:
    queue = JobRoutingQueue(
        trading_queue=RedisJobQueue(settings.redis_url, settings.trading_queue_name),
        ingestion_queue=RedisJobQueue(settings.redis_url, settings.ingestion_queue_name),
    )
    claim_store = RedisScheduleClaimStore(
        settings.redis_url,
        settings.schedule_claim_prefix,
        settings.schedule_claim_ttl_seconds,
    )
    process_state = RedisProcessState(
        settings.redis_url,
        scheduler_heartbeat_ttl_seconds=max(30, settings.scheduler_poll_seconds * 3),
    )
    run_repository = PostgresScheduledRunRepository(settings.database_url)
    runtime_settings = PostgresRuntimeSettings(settings.database_url)

    def scheduler_plans():
        values = runtime_settings.values()
        return default_scheduler_plans(
            player_stats_enabled=settings.player_stats_schedule_enabled,
            player_stats_run_hour_utc=int(values.get("player_stats_schedule_hour_utc", settings.player_stats_schedule_hour_utc)),
            player_stats_league=int(values.get("player_stats_schedule_league", settings.player_stats_schedule_league)),
            player_stats_season=int(values.get("player_stats_schedule_season", settings.player_stats_schedule_season)),
            bet365_enabled=(settings.bet365_schedule_enabled and settings.bet365_browser_enabled),
            bet365_interval_minutes=int(values.get("bet365_schedule_interval_minutes", 15)),
            bet365_live_enabled=(settings.bet365_live_schedule_enabled and settings.bet365_browser_enabled),
            bet365_live_interval_minutes=int(values.get("bet365_live_schedule_interval_minutes", settings.bet365_live_schedule_interval_minutes)),
            twitter_injury_enabled=(
                settings.twitter_injury_schedule_enabled
                and settings.twitter_policy_acknowledged
                and bool(settings.twitter_bearer_token)
                and bool(settings.twitter_search_query)
            ),
            twitter_injury_interval_minutes=int(values.get("twitter_injury_schedule_interval_minutes", settings.twitter_injury_schedule_interval_minutes)),
            twitter_query_key=settings.twitter_query_key,
            market_freezes_enabled=settings.match_freeze_schedule_enabled,
        )

    scheduler = SchedulerService(
        queue=queue,
        claim_store=claim_store,
        control_store=process_state,
        run_repository=run_repository,
        plan_provider=scheduler_plans,
    )
    return SchedulerProcess(
        scheduler=scheduler,
        status_reporter=process_state,
        housekeeping=lambda as_of: run_repository.reconcile_stale_runs(
            as_of,
            stale_after=timedelta(seconds=settings.stale_running_job_seconds),
        ),
        social_dispatcher=DueSocialSubscriptionDispatcher(
            repository=PostgresSocialRepository(settings.database_url),
            queue=queue,
            claim_store=claim_store,
            control_store=process_state,
            run_repository=run_repository,
        ),
    )


def build_worker_process(settings: Settings) -> WorkerProcess:
    queue = RedisJobQueue(settings.redis_url, settings.queue_name)
    retry_queue = RedisRetryQueue(
        settings.redis_url,
        retry_queue_name=settings.retry_queue_name,
        main_queue_name=settings.queue_name,
    )
    runner = WorkerJobRunner(
        {
            **_market_handlers(settings),
            **_ingestion_handlers(settings),
            **_admin_handlers(settings),
        }
    )
    return WorkerProcess(
        queue=queue,
        retry_queue=retry_queue,
        runner=runner,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
        operation_reporter=PostgresOperationRunReporter(
            settings.database_url,
            scheduled_realtime_max_lag_seconds=(
                settings.scheduled_realtime_max_lag_seconds
            ),
        ),
        active_job_reporter=RedisProcessState(
            settings.redis_url,
            active_job_ttl_seconds=max(
                60,
                round(settings.bet365_job_timeout_seconds) + 60,
                settings.stale_running_job_seconds + 60,
            ),
            active_job_key=f"stockball:dev:worker:active-job:{settings.queue_name}",
        ),
        isolated_job_timeouts={
            JobType.INGEST_BET365_ODDS: settings.bet365_job_timeout_seconds,
        },
    )


def _market_handlers(settings: Settings) -> dict:
    """Recurring synthetic-trading jobs routed to the trading queue."""
    topup_repository = PostgresTopupRepository(settings.database_url)
    return {
        JobType.APPLY_TOPUPS: TopupJobHandler(
            topup_service=TopupService(
                trading_engine_client=trading_engine_client(settings),
                policy_store=topup_repository,
                audit_store=topup_repository,
            ),
            synthetic_policy_provisioner=topup_repository,
        ),
        JobType.SYNTHETIC_TRADER_TICK: SyntheticTraderTickJobHandler(
            synthetic_trader_service=build_synthetic_trader_service(settings)
        ),
        JobType.CHECK_MARKET_FREEZES: CheckMarketFreezesJobHandler(
            match_freeze_service=build_match_freeze_service(settings)
        ),
    }


def _ingestion_handlers(settings: Settings) -> dict:
    """External data ingestion jobs routed to the ingestion queue."""
    fbref = fbref_settings(settings)
    social_repository = PostgresSocialRepository(settings.database_url)
    social_source_handler = build_social_source_handler(social_repository)
    handlers: dict = {
        JobType.INGEST_PLAYERS: IngestPlayersJobHandler(
            player_seed_service=build_player_seed_service(fbref)
        ),
        JobType.INGEST_FIXTURES: IngestFixturesJobHandler(
            fixture_ingestion_service=build_fixture_ingestion_service(fbref)
        ),
        JobType.INGEST_PLAYER_STATS: IngestPlayerStatsJobHandler(
            stats_ingestion_service=build_player_stats_ingestion_service(fbref)
        ),
        JobType.INGEST_BET365_ODDS: IngestBet365OddsJobHandler(
            betting_market_ingestion_service=build_bet365_ingestion_service(settings)
        ),
        JobType.INGEST_SOCIAL_SOURCE: social_source_handler,
        JobType.INGEST_SOCIAL_FEEDS: IngestSocialFeedsJobHandler(
            repository=social_repository,
            source_handler=social_source_handler,
        ),
        JobType.PROCESS_SOCIAL_DOCUMENTS: ProcessSocialDocumentsJobHandler(social_repository),
        JobType.AGGREGATE_SOCIAL_SIGNALS: AggregateSocialSignalsJobHandler(social_repository),
    }
    if settings.twitter_search_query:
        handlers[JobType.INGEST_TWITTER_INJURIES] = IngestTwitterInjuriesJobHandler(
            twitter_injury_ingestion_service=build_twitter_injury_ingestion_service(settings),
            search_query=settings.twitter_search_query,
        )
    return handlers


def _admin_handlers(settings: Settings) -> dict:
    """One-off operations triggered from the admin console."""
    engine = trading_engine_client(settings)
    return {
        JobType.IMPORT_MARKET_VALUES: FunctionJobHandler(
            JobType.IMPORT_MARKET_VALUES,
            market_value_import_handler(build_market_value_import_service(settings)),
        ),
        JobType.SEED_PLAYER_SHARES: FunctionJobHandler(
            JobType.SEED_PLAYER_SHARES, seed_player_shares_handler(engine)
        ),
        JobType.SPAWN_SYNTHETIC_TRADERS: FunctionJobHandler(
            JobType.SPAWN_SYNTHETIC_TRADERS,
            spawn_traders_handler(build_synthetic_trader_spawner(settings)),
        ),
        JobType.BOOTSTRAP_SYNTHETIC_PORTFOLIOS: FunctionJobHandler(
            JobType.BOOTSTRAP_SYNTHETIC_PORTFOLIOS,
            bootstrap_portfolios_handler(
                SyntheticPortfolioBootstrapService(
                    PostgresSyntheticPortfolioBootstrapRepository(settings.database_url, engine)
                )
            ),
        ),
        JobType.SET_SYNTHETIC_TRADER_STATUS: FunctionJobHandler(
            JobType.SET_SYNTHETIC_TRADER_STATUS,
            set_bot_status_handler(
                PostgresSyntheticTraderRepository(
                    settings.database_url,
                    social_signals_enabled=settings.social_signals_enabled,
                    social_signal_max_age_seconds=settings.social_signal_max_age_seconds,
                )
            ),
        ),
    }
