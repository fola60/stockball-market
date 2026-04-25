from __future__ import annotations

import argparse
import logging

from app.clients import HttpTradingEngineClient
from app.config import PlayerSeedSettings, Settings
from app.ingestion.players import FootballDataClient, PlayerSeedService, PostgresPlayerRepository
from app.jobs import JobType, IngestPlayersJobHandler, TopupJobHandler, WorkerJobRunner, WorkerProcess
from app.queue import RedisJobQueue, RedisRetryQueue, RedisScheduleClaimStore
from app.scheduler import SchedulerProcess, SchedulerService
from app.topups import PostgresTopupRepository, TopupService


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "seed-players":
        settings = PlayerSeedSettings.from_env()
        _configure_logging(args.log_level)
        result = _build_player_seed_service(settings).seed_players(args.competition)
        logging.getLogger(__name__).info(
            "seeded players from football-data.org",
            extra={
                "competition": args.competition,
                "fetched_players": result.fetched_players,
                "upserted_players": result.upserted_players,
                "clubs_seen": result.clubs_seen,
            },
        )
        print(
            f"seeded {result.upserted_players} players "
            f"from {result.clubs_seen} clubs for {args.competition}"
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
        help="ingest current Premier League squads from football-data.org into players",
    )
    seed_players.add_argument(
        "--competition",
        default="PL",
        help="football-data.org competition code to seed, default: PL",
    )
    seed_players.add_argument(
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
    handlers = {
        JobType.APPLY_TOPUPS: TopupJobHandler(topup_service=topup_service),
    }
    if settings.football_data_api_token:
        handlers[JobType.INGEST_PLAYERS] = IngestPlayersJobHandler(
            player_seed_service=_build_player_seed_service(
                PlayerSeedSettings(
                    database_url=settings.database_url,
                    football_data_api_token=settings.football_data_api_token,
                    football_data_api_base_url=settings.football_data_api_base_url,
                    football_data_request_interval_seconds=(
                        settings.football_data_request_interval_seconds
                    ),
                )
            )
        )
    runner = WorkerJobRunner(handlers)
    return WorkerProcess(
        queue=queue,
        retry_queue=retry_queue,
        runner=runner,
        retry_delay_seconds=settings.retry_delay_seconds,
        max_attempts=settings.max_attempts,
    )


def _build_player_seed_service(settings: PlayerSeedSettings) -> PlayerSeedService:
    return PlayerSeedService(
        client=FootballDataClient(
            api_token=settings.football_data_api_token,
            base_url=settings.football_data_api_base_url,
            request_interval_seconds=settings.football_data_request_interval_seconds,
        ),
        repository=PostgresPlayerRepository(settings.database_url),
    )


if __name__ == "__main__":
    raise SystemExit(main())
