"""The `stockball-worker` command line: maps each subcommand to its handler."""

from __future__ import annotations

from typing import Callable

from app.cli import build_parser

from .commands import ingestion, market, runtime

COMMANDS: dict[str, Callable[..., int]] = {
    # Long-running processes
    "scheduler": runtime.scheduler,
    "schedule-once": runtime.schedule_once,
    "worker": runtime.worker,
    "work-once": runtime.work_once,
    # External data ingestion
    "seed-players": ingestion.seed_players,
    "ingest-fixtures": ingestion.ingest_fixtures,
    "ingest-player-stats": ingestion.ingest_player_stats,
    "import-market-values": ingestion.import_market_values,
    "ingest-bet365-odds": ingestion.ingest_bet365_odds,
    "sync-twitter-injury-registry": ingestion.sync_twitter_injury_registry,
    "ingest-twitter-injuries": ingestion.ingest_twitter_injuries,
    # Market setup and seeding
    "seed-player-shares": market.seed_player_shares,
    "spawn-synthetic-traders": market.spawn_synthetic_traders,
    "bootstrap-synthetic-portfolios": market.bootstrap_synthetic_portfolios,
    "bootstrap-dev-market": market.bootstrap_dev_market,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = COMMANDS.get(args.command)
    if command is None:
        parser.error(f"unsupported command: {args.command}")
    return command(args)
