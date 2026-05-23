from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from app.clients import HttpTradingEngineClient
from app.config import FbrefIngestionSettings, DatabaseSettings, Settings
from app.ingestion.fbref import FbrefAccessDeniedError, FbrefClient
from app.ingestion.fixtures import FixtureIngestionService, PostgresFixtureRepository
from app.ingestion.market_values import MarketValueImportService, PostgresMarketValueRepository
from app.ingestion.players import PlayerSeedService, PostgresPlayerRepository
from app.ingestion.stats import PlayerStatsIngestionService, PostgresPlayerStatsRepository
from app.jobs import (
    IngestFixturesJobHandler,
    IngestPlayerStatsJobHandler,
    IngestPlayersJobHandler,
    JobType,
    SyntheticTraderTickJobHandler,
    TopupJobHandler,
    WorkerJobRunner,
    WorkerProcess,
)
from app.queue import RedisJobQueue, RedisRetryQueue, RedisScheduleClaimStore
from app.scheduler import SchedulerProcess, SchedulerService
from app.synthetic_traders import (
    PostgresSyntheticTraderRepository,
    SyntheticTraderService,
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
    return parser


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


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
    scheduler = SchedulerService(queue=queue, claim_store=claim_store)
    return SchedulerProcess(scheduler=scheduler)


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
    handlers = {
        JobType.APPLY_TOPUPS: TopupJobHandler(topup_service=topup_service),
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
    runner = WorkerJobRunner(handlers)
    return WorkerProcess(
        queue=queue,
        retry_queue=retry_queue,
        runner=runner,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
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


def _build_synthetic_trader_service(settings: Settings) -> SyntheticTraderService:
    return SyntheticTraderService(
        repository=PostgresSyntheticTraderRepository(settings.database_url),
        trading_engine_client=HttpTradingEngineClient(
            settings.trading_engine_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        ),
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
