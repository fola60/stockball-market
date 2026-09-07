from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from app.clients import ApiClientError, ApiUnavailableError, HttpApiClient, HttpTradingEngineClient
from app.config import FbrefIngestionSettings, DatabaseSettings, Settings
from app.ingestion.fbref import FbrefAccessDeniedError, FbrefClient
from app.ingestion.betting_markets import (
    Bet365Client,
    Bet365IngestionError,
    BettingMarketIngestionService,
    PostgresBettingMarketRepository,
)
from app.ingestion.fixtures import FixtureIngestionService, PostgresFixtureRepository
from app.ingestion.market_values import MarketValueImportService, PostgresMarketValueRepository
from app.ingestion.players import PlayerSeedService, PostgresPlayerRepository
from app.ingestion.stats import PlayerStatsIngestionService, PostgresPlayerStatsRepository
from app.ingestion.social.twitter import (
    PostgresTwitterInjuryRepository,
    TwitterIngestionError,
    TwitterInjuryIngestionService,
    TwitterRecentSearchClient,
    load_registry,
)
from app.jobs import (
    Bet365IngestionMode,
    IngestFixturesJobHandler,
    IngestBet365OddsJobHandler,
    IngestPlayerStatsJobHandler,
    IngestPlayersJobHandler,
    IngestTwitterInjuriesJobHandler,
    JobType,
    SyntheticTraderTickJobHandler,
    TopupJobHandler,
    WorkerJobRunner,
    WorkerProcess,
    FunctionJobHandler,
)
from app.jobs.dev_handlers import (
    bootstrap_portfolios_handler,
    market_value_import_handler,
    seed_player_shares_handler,
    set_bot_status_handler,
    spawn_traders_handler,
)
from app.dev_operations import PostgresOperationRunReporter, PostgresScheduledRunRepository
from app.queue import RedisJobQueue, RedisRetryQueue, RedisScheduleClaimStore
from app.process_state import RedisProcessState
from app.scheduler import SchedulerProcess, SchedulerService
from app.scheduler.models import default_scheduler_plans
from app.synthetic_traders import (
    BootstrapAllocationError,
    BotStatus,
    PostgresSyntheticTraderRepository,
    PostgresSyntheticPortfolioBootstrapRepository,
    SpawnNameStyle,
    SpawnSyntheticTraderCommand,
    StrategyEngine,
    SyntheticTraderConfigNotFoundError,
    SyntheticTraderService,
    SyntheticTraderSpawner,
    SyntheticPortfolioBootstrapService,
)
from app.topups import PostgresTopupRepository, TopupService


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "seed-players":
        settings = FbrefIngestionSettings.from_env()
        _configure_logging(args.log_level)
        try:
            result = _build_player_seed_service(settings).seed_players(args.league, args.season)
        except FbrefAccessDeniedError as error:
            _print_provider_access_error(error)
            return 1
        logging.getLogger(__name__).info(
            "seeded players from FBref",
            extra={
                "league": args.league,
                "season": args.season,
                "fetched_players": result.fetched_players,
                "upserted_players": result.upserted_players,
                "clubs_seen": result.clubs_seen,
            },
        )
        print(
            f"seeded {result.upserted_players} players "
            f"from {result.clubs_seen} clubs for league {args.league} season {args.season}"
        )
        return 0

    if args.command == "ingest-fixtures":
        settings = FbrefIngestionSettings.from_env()
        _configure_logging(args.log_level)
        try:
            result = _build_fixture_ingestion_service(settings).ingest_fixtures(
                league=args.league,
                season=args.season,
                from_date=_optional_date_arg(args.from_date),
                to_date=_optional_date_arg(args.to_date),
            )
        except FbrefAccessDeniedError as error:
            _print_provider_access_error(error)
            return 1
        print(
            f"upserted {result.upserted_fixtures} fixtures "
            f"for league {args.league} season {args.season}"
        )
        return 0

    if args.command == "ingest-player-stats":
        settings = FbrefIngestionSettings.from_env()
        _configure_logging(args.log_level)
        try:
            result = _build_player_stats_ingestion_service(
                settings
            ).ingest_player_stats(
                league=args.league,
                season=args.season,
                stat_types=tuple(args.stat_type) if args.stat_type else None,
            )
        except FbrefAccessDeniedError as error:
            _print_provider_access_error(error)
            return 1
        print(
            f"upserted {result.upserted_observations} player-stat observations "
            f"for league {args.league} season {args.season}; "
            f"matched {result.matched_players} players"
        )
        return 0

    if args.command == "import-market-values":
        settings = DatabaseSettings.from_env()
        _configure_logging(args.log_level)
        result = _build_market_value_import_service(settings).import_transfermarkt_csv(
            valuations_csv_path=Path(args.valuations_csv),
            players_csv_path=None if args.players_csv is None else Path(args.players_csv),
            source=args.source,
            currency=args.currency,
        )
        print(
            f"imported market values batch {result.batch_id}: "
            f"{result.matched_rows} matched, "
            f"{result.ambiguous_rows} ambiguous, "
            f"{result.unmatched_rows} unmatched, "
            f"{result.rejected_rows} rejected"
        )
        return 0

    if args.command == "seed-player-shares":
        settings = Settings.from_env()
        _configure_logging(args.log_level)
        result = HttpTradingEngineClient(
            settings.trading_engine_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        ).seed_player_shares()
        print(
            f"seeded player shares: {result.created_count} created, "
            f"{result.skipped_existing_count} skipped existing, "
            f"{result.market_value_priced_count} market-value priced, "
            f"{result.fallback_priced_count} fallback priced"
        )
        return 0

    if args.command == "ingest-bet365-odds":
        settings = Settings.from_env()
        _configure_logging(args.log_level)
        try:
            service = _build_bet365_ingestion_service(
                settings,
                max_matches_override=args.max_matches,
            )
            if Bet365IngestionMode(args.mode) is Bet365IngestionMode.LIVE:
                result = service.ingest_live_markets(datetime.now(UTC))
            else:
                result = service.ingest_pre_match_markets(args.league)
        except Bet365IngestionError as error:
            print(f"Bet365 odds ingestion unavailable: {error}")
            return 1
        print(f"upserted {result.upserted_observations} Bet365 market observations")
        return 0

    if args.command == "sync-twitter-injury-registry":
        settings = DatabaseSettings.from_env()
        _configure_logging(args.log_level)
        repository = PostgresTwitterInjuryRepository(settings.database_url)
        result = repository.sync_registry(load_registry(Path(args.registry)))
        print(
            f"synced {result.source_accounts} X source accounts and "
            f"{result.player_aliases} player aliases"
        )
        return 0

    if args.command == "ingest-twitter-injuries":
        settings = Settings.from_env()
        _configure_logging(args.log_level)
        query = args.query or settings.twitter_search_query
        if not query:
            print(
                "Twitter injury ingestion unavailable: set STOCKBALL_TWITTER_SEARCH_QUERY "
                "or pass --query"
            )
            return 1
        try:
            result = _build_twitter_injury_ingestion_service(settings).ingest_recent(
                query,
                args.query_key or settings.twitter_query_key,
            )
        except (TwitterIngestionError, ValueError) as error:
            print(f"Twitter injury ingestion unavailable: {error}")
            return 1
        print(
            f"processed {result.fetched_posts} X posts across {result.pages_fetched} pages: "
            f"{result.persisted_posts} new observations, "
            f"{result.episode_updates} episode updates, "
            f"{result.ambiguous_posts} ambiguous player matches"
        )
        return 0

    if args.command == "spawn-synthetic-traders":
        settings = Settings.from_env()
        _configure_logging(args.log_level)
        try:
            result = _build_synthetic_trader_spawner(settings).spawn(
                SpawnSyntheticTraderCommand(
                    count=args.count,
                    handle_prefix=args.handle_prefix,
                    display_name_prefix=args.display_name_prefix,
                    config_key=args.config_key,
                    strategy_engine=(
                        None
                        if args.strategy_engine is None
                        else StrategyEngine(args.strategy_engine)
                    ),
                    name_style=SpawnNameStyle(args.name_style),
                    random_seed=args.random_seed,
                    start_index=args.start_index,
                    status=BotStatus(args.status),
                )
            )
        except SyntheticTraderConfigNotFoundError as error:
            print(str(error))
            return 1
        except ValueError as error:
            print(str(error))
            return 1
        except (ApiUnavailableError, ApiClientError) as error:
            print(f"failed to provision synthetic trader account: {error}")
            return 1

        print(
            f"spawned {result.spawned_count}/{result.requested_count} synthetic traders "
            f"using config {result.config_key}"
        )
        for trader in result.spawned:
            print(
                f"{trader.handle} account={trader.account_id} "
                f"portfolio={trader.portfolio_id} bot={trader.bot_id}"
            )
        return 0

    if args.command == "bootstrap-synthetic-portfolios":
        settings = DatabaseSettings.from_env()
        _configure_logging(args.log_level)
        try:
            result = SyntheticPortfolioBootstrapService(
                PostgresSyntheticPortfolioBootstrapRepository(settings.database_url)
            ).bootstrap(
                bot_ids=tuple(args.bot_id or ()),
                all_active_synthetic_bots=args.all_active_synthetic_bots,
                seed=args.seed,
                min_holders_per_player=args.min_holders_per_player,
                max_player_supply_per_bot=args.max_player_supply_per_bot,
                reserve_supply_percent=args.reserve_supply_percent,
                max_positions_per_bot=args.max_positions_per_bot,
                dry_run=args.dry_run,
            )
        except BootstrapAllocationError as error:
            print(f"bootstrap allocation failed: {error}")
            return 1
        mode = "dry-run" if args.dry_run else "committed"
        print(
            f"bootstrap synthetic portfolios ({mode}): seed={result.seed}, "
            f"bots={len(result.selected_bot_ids)}, "
            f"instruments={result.instruments_processed}, "
            f"bot_shares={result.bot_shares}, reserve_shares={result.reserve_shares}, "
            f"positions={result.created_positions}, skipped={len(result.skipped_instruments)}"
        )
        for symbol, reason in result.skipped_instruments:
            print(f"skipped {symbol}: {reason}")
        return 0

    settings = Settings.from_env()
    _configure_logging(settings.log_level)

    if args.command == "scheduler":
        _build_scheduler_process(settings).run_forever(settings.scheduler_poll_seconds)
        return 0

    if args.command == "schedule-once":
        _build_scheduler_process(settings).run_once()
        return 0

    if args.command == "worker":
        _build_worker_process(settings).run_forever(settings.worker_block_seconds)
        return 0

    if args.command == "work-once":
        _build_worker_process(settings).run_once(settings.worker_block_seconds)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stockball worker service")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("scheduler", help="run the recurring scheduler loop")
    subcommands.add_parser("schedule-once", help="enqueue due recurring jobs once")
    subcommands.add_parser("worker", help="run the worker consumer loop")
    subcommands.add_parser("work-once", help="consume and execute at most one queued job")
    seed_players = subcommands.add_parser(
        "seed-players",
        help="ingest league players from FBref into players",
    )
    seed_players.add_argument(
        "--league",
        type=int,
        default=9,
        help="FBref competition id, default: 9",
    )
    seed_players.add_argument(
        "--season",
        type=int,
        required=True,
        help="season year",
    )
    seed_players.add_argument(
        "--log-level",
        default="INFO",
        help="log level for the one-off seed command, default: INFO",
    )
    ingest_fixtures = subcommands.add_parser(
        "ingest-fixtures",
        help="ingest fixtures from FBref",
    )
    ingest_fixtures.add_argument("--league", type=int, default=9, help="FBref competition id")
    ingest_fixtures.add_argument("--season", type=int, required=True, help="season year")
    ingest_fixtures.add_argument("--from-date", help="optional start date YYYY-MM-DD")
    ingest_fixtures.add_argument("--to-date", help="optional end date YYYY-MM-DD")
    ingest_fixtures.add_argument(
        "--log-level",
        default="INFO",
        help="log level for the one-off ingestion command, default: INFO",
    )
    ingest_stats = subcommands.add_parser(
        "ingest-player-stats",
        help="ingest season player stat tables from FBref",
    )
    ingest_stats.add_argument("--league", type=int, default=9, help="FBref competition id")
    ingest_stats.add_argument("--season", type=int, required=True, help="season start year")
    ingest_stats.add_argument(
        "--stat-type",
        action="append",
        choices=("standard", "shooting", "passing", "defense", "keeper"),
        help="FBref stat table to ingest; repeat to ingest multiple tables",
    )
    ingest_stats.add_argument(
        "--log-level",
        default="INFO",
        help="log level for the one-off ingestion command, default: INFO",
    )
    ingest_bet365 = subcommands.add_parser(
        "ingest-bet365-odds",
        help="ingest Bet365 pre-match or live match and player markets",
    )
    ingest_bet365.add_argument(
        "--mode",
        choices=[mode.value for mode in Bet365IngestionMode],
        default=Bet365IngestionMode.PRE_MATCH.value,
        help="PRE_MATCH discovers fixtures; LIVE refreshes known active event URLs",
    )
    ingest_bet365.add_argument(
        "--league",
        help="website competition name; PL maps to Premier League",
    )
    ingest_bet365.add_argument(
        "--max-matches",
        type=_positive_int,
        help="maximum fixture pages to inspect during this run",
    )
    ingest_bet365.add_argument("--log-level", default="INFO")
    sync_twitter_registry = subcommands.add_parser(
        "sync-twitter-injury-registry",
        help="sync manually reviewed X source accounts and player aliases from JSON",
    )
    sync_twitter_registry.add_argument("--registry", required=True, help="path to registry JSON")
    sync_twitter_registry.add_argument("--log-level", default="INFO")
    ingest_twitter_injuries = subcommands.add_parser(
        "ingest-twitter-injuries",
        help="poll approved X API recent search and update player injury episodes",
    )
    ingest_twitter_injuries.add_argument(
        "--query",
        help="X recent-search query; defaults to STOCKBALL_TWITTER_SEARCH_QUERY",
    )
    ingest_twitter_injuries.add_argument(
        "--query-key",
        help="stable cursor key; defaults to STOCKBALL_TWITTER_QUERY_KEY or a query hash",
    )
    ingest_twitter_injuries.add_argument("--log-level", default="INFO")
    import_market_values = subcommands.add_parser(
        "import-market-values",
        help="import Transfermarkt-derived market values from CSV files",
    )
    import_market_values.add_argument(
        "--valuations-csv",
        required=True,
        help="path to player_valuations.csv",
    )
    import_market_values.add_argument(
        "--players-csv",
        help="optional path to players.csv for names, clubs, DOBs, and source URLs",
    )
    import_market_values.add_argument(
        "--source",
        default="transfermarkt_csv",
        help="source label to store with import rows, default: transfermarkt_csv",
    )
    import_market_values.add_argument(
        "--currency",
        default="EUR",
        help="currency for market values, default: EUR",
    )
    import_market_values.add_argument(
        "--log-level",
        default="INFO",
        help="log level for the one-off import command, default: INFO",
    )
    seed_player_shares = subcommands.add_parser(
        "seed-player-shares",
        help="create PLAYER_SHARE instruments from players and market values",
    )
    seed_player_shares.add_argument(
        "--log-level",
        default="INFO",
        help="log level for the one-off seed command, default: INFO",
    )
    spawn_synthetic_traders = subcommands.add_parser(
        "spawn-synthetic-traders",
        help="create synthetic trader accounts through the API and attach worker bot configs",
    )
    spawn_config_selector = spawn_synthetic_traders.add_mutually_exclusive_group(required=True)
    spawn_config_selector.add_argument(
        "--config-key",
        help="exact synthetic_trader_bot_configs.config_key to attach",
    )
    spawn_config_selector.add_argument(
        "--strategy-engine",
        choices=[engine.value for engine in StrategyEngine],
        help="strategy engine to spawn using its default seeded config",
    )
    spawn_synthetic_traders.add_argument(
        "--count",
        type=int,
        required=True,
        help="number of bots to create",
    )
    spawn_synthetic_traders.add_argument(
        "--handle-prefix",
        help="prefix for account handles and bot keys when --name-style NUMBERED is used",
    )
    spawn_synthetic_traders.add_argument(
        "--display-name-prefix",
        help="prefix for display names when --name-style NUMBERED is used",
    )
    spawn_synthetic_traders.add_argument(
        "--name-style",
        choices=[name_style.value for name_style in SpawnNameStyle],
        default=SpawnNameStyle.PERSONA.value,
        help="public account naming style, default: PERSONA",
    )
    spawn_synthetic_traders.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="first numeric suffix to use, default: 1",
    )
    spawn_synthetic_traders.add_argument(
        "--random-seed",
        type=int,
        help="optional seed for reproducible per-bot config randomization",
    )
    spawn_synthetic_traders.add_argument(
        "--status",
        choices=[status.value for status in BotStatus],
        default=BotStatus.ACTIVE.value,
        help="initial bot status, default: ACTIVE",
    )
    spawn_synthetic_traders.add_argument(
        "--log-level",
        default="INFO",
        help="log level for the one-off spawn command, default: INFO",
    )
    bootstrap_portfolios = subcommands.add_parser(
        "bootstrap-synthetic-portfolios",
        help="issue seeded player-share supply to synthetic traders and the reserve",
    )
    bot_selector = bootstrap_portfolios.add_mutually_exclusive_group(required=True)
    bot_selector.add_argument(
        "--bot-id",
        action="append",
        type=UUID,
        help="synthetic trader bot UUID; repeat to select multiple bots",
    )
    bot_selector.add_argument(
        "--all-active-synthetic-bots",
        action="store_true",
        help="select every active non-social synthetic trader",
    )
    bootstrap_portfolios.add_argument("--seed", type=int)
    bootstrap_portfolios.add_argument(
        "--min-holders-per-player", type=_positive_int, default=3
    )
    bootstrap_portfolios.add_argument(
        "--max-player-supply-per-bot", type=_percentage_up_to_100, default=Decimal("20")
    )
    bootstrap_portfolios.add_argument(
        "--reserve-supply-percent", type=_percentage, default=Decimal("10")
    )
    bootstrap_portfolios.add_argument(
        "--max-positions-per-bot", type=_positive_int, default=100
    )
    bootstrap_portfolios.add_argument("--dry-run", action="store_true")
    bootstrap_portfolios.add_argument("--log-level", default="INFO")
    return parser


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _percentage(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal percentage") from error
    if not Decimal("0") < parsed < Decimal("100"):
        raise argparse.ArgumentTypeError("value must be greater than 0 and less than 100")
    return parsed


def _percentage_up_to_100(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal percentage") from error
    if not Decimal("0") < parsed <= Decimal("100"):
        raise argparse.ArgumentTypeError("value must be greater than 0 and at most 100")
    return parsed


def _print_provider_access_error(error: FbrefAccessDeniedError) -> None:
    logging.getLogger(__name__).error("FBref ingestion access denied", extra={"error": str(error)})
    print(
        "FBref denied this ingestion request. "
    )


def _build_scheduler_process(settings: Settings) -> SchedulerProcess:
    queue = RedisJobQueue(settings.redis_url, settings.queue_name)
    claim_store = RedisScheduleClaimStore(
        settings.redis_url,
        settings.schedule_claim_prefix,
        settings.schedule_claim_ttl_seconds,
    )
    process_state = RedisProcessState(
        settings.redis_url,
        scheduler_heartbeat_ttl_seconds=max(30, settings.scheduler_poll_seconds * 3),
    )
    scheduler = SchedulerService(
        queue=queue,
        claim_store=claim_store,
        control_store=process_state,
        run_repository=PostgresScheduledRunRepository(settings.database_url),
        plans=default_scheduler_plans(
            player_stats_enabled=settings.player_stats_schedule_enabled,
            player_stats_run_hour_utc=settings.player_stats_schedule_hour_utc,
            player_stats_league=settings.player_stats_schedule_league,
            player_stats_season=settings.player_stats_schedule_season,
            bet365_enabled=(
                settings.bet365_schedule_enabled
                and settings.bet365_browser_enabled
            ),
            bet365_live_enabled=(
                settings.bet365_live_schedule_enabled
                and settings.bet365_browser_enabled
            ),
            bet365_live_interval_minutes=settings.bet365_live_schedule_interval_minutes,
            twitter_injury_enabled=(
                settings.twitter_injury_schedule_enabled
                and settings.twitter_policy_acknowledged
                and bool(settings.twitter_bearer_token)
                and bool(settings.twitter_search_query)
            ),
            twitter_injury_interval_minutes=settings.twitter_injury_schedule_interval_minutes,
            twitter_query_key=settings.twitter_query_key,
        ),
    )
    return SchedulerProcess(scheduler=scheduler, status_reporter=process_state)


def _build_worker_process(settings: Settings) -> WorkerProcess:
    queue = RedisJobQueue(settings.redis_url, settings.queue_name)
    retry_queue = RedisRetryQueue(
        settings.redis_url,
        retry_queue_name=settings.retry_queue_name,
        main_queue_name=settings.queue_name,
    )
    topup_repository = PostgresTopupRepository(settings.database_url)
    topup_service = TopupService(
        trading_engine_client=HttpTradingEngineClient(
            settings.trading_engine_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        ),
        policy_store=topup_repository,
        audit_store=topup_repository,
    )
    synthetic_trader_service = _build_synthetic_trader_service(settings)
    trading_engine_client = HttpTradingEngineClient(
        settings.trading_engine_url,
        timeout_seconds=settings.trading_engine_timeout_seconds,
    )
    synthetic_repository = PostgresSyntheticTraderRepository(settings.database_url)
    handlers = {
        JobType.APPLY_TOPUPS: TopupJobHandler(
            topup_service=topup_service,
            synthetic_policy_provisioner=topup_repository,
        ),
        JobType.SYNTHETIC_TRADER_TICK: SyntheticTraderTickJobHandler(
            synthetic_trader_service=synthetic_trader_service
        ),
    }
    fbref_settings = FbrefIngestionSettings(
        database_url=settings.database_url,
        base_url=settings.fbref_base_url,
        request_interval_seconds=settings.fbref_request_interval_seconds,
        user_agent=settings.fbref_user_agent,
        cache_ttl_seconds=settings.fbref_cache_ttl_seconds,
    )
    handlers[JobType.INGEST_PLAYERS] = IngestPlayersJobHandler(
        player_seed_service=_build_player_seed_service(fbref_settings)
    )
    handlers[JobType.INGEST_FIXTURES] = IngestFixturesJobHandler(
        fixture_ingestion_service=_build_fixture_ingestion_service(fbref_settings)
    )
    handlers[JobType.INGEST_PLAYER_STATS] = IngestPlayerStatsJobHandler(
        stats_ingestion_service=_build_player_stats_ingestion_service(fbref_settings)
    )
    handlers[JobType.INGEST_BET365_ODDS] = IngestBet365OddsJobHandler(
        betting_market_ingestion_service=_build_bet365_ingestion_service(settings)
    )
    handlers[JobType.IMPORT_MARKET_VALUES] = FunctionJobHandler(
        JobType.IMPORT_MARKET_VALUES,
        market_value_import_handler(_build_market_value_import_service(settings)),
    )
    handlers[JobType.SEED_PLAYER_SHARES] = FunctionJobHandler(
        JobType.SEED_PLAYER_SHARES, seed_player_shares_handler(trading_engine_client)
    )
    handlers[JobType.SPAWN_SYNTHETIC_TRADERS] = FunctionJobHandler(
        JobType.SPAWN_SYNTHETIC_TRADERS,
        spawn_traders_handler(_build_synthetic_trader_spawner(settings)),
    )
    handlers[JobType.BOOTSTRAP_SYNTHETIC_PORTFOLIOS] = FunctionJobHandler(
        JobType.BOOTSTRAP_SYNTHETIC_PORTFOLIOS,
        bootstrap_portfolios_handler(
            SyntheticPortfolioBootstrapService(
                PostgresSyntheticPortfolioBootstrapRepository(settings.database_url)
            )
        ),
    )
    handlers[JobType.SET_SYNTHETIC_TRADER_STATUS] = FunctionJobHandler(
        JobType.SET_SYNTHETIC_TRADER_STATUS,
        set_bot_status_handler(synthetic_repository),
    )
    if settings.twitter_search_query:
        handlers[JobType.INGEST_TWITTER_INJURIES] = IngestTwitterInjuriesJobHandler(
            twitter_injury_ingestion_service=_build_twitter_injury_ingestion_service(settings),
            search_query=settings.twitter_search_query,
        )
    runner = WorkerJobRunner(handlers)
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
            ),
        ),
        isolated_job_timeouts={
            JobType.INGEST_BET365_ODDS: settings.bet365_job_timeout_seconds,
        },
    )


def _build_player_seed_service(settings: FbrefIngestionSettings) -> PlayerSeedService:
    return PlayerSeedService(
        client=_build_fbref_client(settings),
        repository=PostgresPlayerRepository(settings.database_url),
    )


def _build_fixture_ingestion_service(
    settings: FbrefIngestionSettings,
) -> FixtureIngestionService:
    return FixtureIngestionService(
        client=_build_fbref_client(settings),
        repository=PostgresFixtureRepository(settings.database_url),
    )


def _build_player_stats_ingestion_service(
    settings: FbrefIngestionSettings,
) -> PlayerStatsIngestionService:
    return PlayerStatsIngestionService(
        client=_build_fbref_client(settings),
        repository=PostgresPlayerStatsRepository(settings.database_url),
    )


def _build_market_value_import_service(settings: DatabaseSettings) -> MarketValueImportService:
    return MarketValueImportService(
        repository=PostgresMarketValueRepository(settings.database_url),
    )


def _build_bet365_ingestion_service(
    settings: Settings,
    *,
    max_matches_override: int | None = None,
) -> BettingMarketIngestionService:
    client = Bet365Client(
        browser_enabled=settings.bet365_browser_enabled,
        homepage_url=settings.bet365_website_url,
        competition_name=settings.bet365_competition_name,
        max_matches=(
            max_matches_override
            if max_matches_override is not None
            else settings.bet365_max_matches
        ),
        pre_match_cutoff_minutes=settings.bet365_pre_match_cutoff_minutes,
        request_interval_seconds=settings.bet365_website_navigation_interval_seconds,
        browser_idle_seconds=settings.bet365_browser_idle_seconds,
    )
    return BettingMarketIngestionService(
        client=client,
        repository=PostgresBettingMarketRepository(settings.database_url),
        live_event_window_minutes=settings.bet365_live_event_window_minutes,
        live_event_limit=(
            max_matches_override
            if max_matches_override is not None
            else settings.bet365_max_matches
        ),
    )


def _build_twitter_injury_ingestion_service(settings: Settings) -> TwitterInjuryIngestionService:
    return TwitterInjuryIngestionService(
        client=TwitterRecentSearchClient(
            policy_acknowledged=settings.twitter_policy_acknowledged,
            request_interval_seconds=settings.twitter_request_interval_seconds,
            max_results=settings.twitter_max_results,
            browser_enabled=settings.twitter_browser_enabled,
            browser_user_data_dir=settings.twitter_browser_user_data_dir,
            browser_profile_directory=settings.twitter_browser_profile_directory,
        ),
        repository=PostgresTwitterInjuryRepository(settings.database_url),
        max_pages_per_poll=settings.twitter_max_pages_per_poll,
    )


def _build_synthetic_trader_service(settings: Settings) -> SyntheticTraderService:
    return SyntheticTraderService(
        repository=PostgresSyntheticTraderRepository(settings.database_url),
        trading_engine_client=HttpTradingEngineClient(
            settings.trading_engine_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        ),
    )


def _build_synthetic_trader_spawner(settings: Settings) -> SyntheticTraderSpawner:
    return SyntheticTraderSpawner(
        api_client=HttpApiClient(
            settings.api_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        ),
        repository=PostgresSyntheticTraderRepository(settings.database_url),
    )


def _build_fbref_client(settings: FbrefIngestionSettings) -> FbrefClient:
    print(
        "[DEBUG] Building FbrefClient "
        f"base_url={settings.base_url} "
        f"request_interval_seconds={settings.request_interval_seconds} "
        "cache_ttl_seconds=0"
    )
    return FbrefClient(
        base_url=settings.base_url,
        request_interval_seconds=settings.request_interval_seconds,
        cache_ttl_seconds=0,
    )


def _optional_date_arg(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    return date.fromisoformat(raw_value)


if __name__ == "__main__":
    raise SystemExit(main())
