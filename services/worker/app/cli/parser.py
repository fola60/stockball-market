from __future__ import annotations

import argparse
import math
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.jobs import Bet365IngestionMode
from app.seasons import current_season
from app.synthetic_traders import BotStatus, SpawnNameStyle, StrategyEngine


def build_parser() -> argparse.ArgumentParser:
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
        default=current_season(),
        help="season start year (2026 is 2026-27), default: the season in progress",
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
    ingest_fixtures.add_argument(
        "--season", type=int, default=current_season(), help="season start year (2026 is 2026-27), default: the season in progress"
    )
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
    ingest_stats.add_argument(
        "--season", type=int, default=current_season(), help="season start year (2026 is 2026-27), default: the season in progress"
    )
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
    fotmob = subcommands.add_parser("ingest-fotmob-ratings", help="ingest final FotMob player match ratings")
    fotmob.add_argument("--league", type=_positive_int, default=47, help="FotMob league ID; 47 is Premier League")
    fotmob.add_argument("--season", type=int, default=0, help="season start year, 0 means current")
    fotmob.add_argument("--backfill", action="store_true", help="all finished matches, resuming completed work")
    fotmob.add_argument("--refresh", action="store_true", help="refetch already ingested matches")
    fotmob.add_argument("--max-matches", type=_positive_int)
    fotmob.add_argument("--archive-dir", help="resumable match JSON archive (backfill only)")
    fotmob.add_argument("--log-level", default="INFO")
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
        help="Twitter API recent search and update player injury episodes",
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
        help="select every active synthetic trader",
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
    bootstrap_portfolios.add_argument(
        "--top-player-holder-percent",
        type=_percentage_up_to_100,
        default=Decimal("40"),
        help="share of bots holding the most valuable player, default: 40",
    )
    bootstrap_portfolios.add_argument(
        "--target-seed-value-per-bot", type=_positive_decimal, default=Decimal("250000")
    )
    bootstrap_portfolios.add_argument(
        "--seed-value-jitter-percent", type=_percentage_from_zero, default=Decimal("25")
    )
    bootstrap_portfolios.add_argument(
        "--holder-price-exponent",
        type=_non_negative_float,
        default=1.0,
        help="how holder share falls with price below the top player: 1 linear (default), 0 flat",
    )
    bootstrap_portfolios.add_argument(
        "--risk-limit-headroom-percent",
        type=_percentage_up_to_100,
        default=Decimal("75"),
        help="seed positions stay within this share of each bot's own risk limits, default: 75",
    )
    bootstrap_portfolios.add_argument("--dry-run", action="store_true")
    bootstrap_portfolios.add_argument("--log-level", default="INFO")
    bootstrap_market = subcommands.add_parser(
        "bootstrap-dev-market",
        help="seed and size a complete synthetic development market",
    )
    bootstrap_market.add_argument(
        "--target-trades-per-hour-per-instrument",
        type=_positive_float,
        required=True,
        help="minimum projected hourly trade activity for every active instrument",
    )
    bootstrap_market.add_argument(
        "--max-bots",
        type=_positive_int_or_unlimited,
        default=5000,
        help="fleet safety cap; use 'unlimited' or 'none' to disable it, default: 5000",
    )
    bootstrap_market.add_argument(
        "--popularity-headroom",
        type=_non_negative_float,
        default=0.25,
        help="extra fleet capacity distributed toward popular instruments, default: 0.25",
    )
    bootstrap_market.add_argument("--market-value-weight", type=_non_negative_float, default=0.45)
    bootstrap_market.add_argument("--stats-weight", type=_non_negative_float, default=0.45)
    bootstrap_market.add_argument("--social-weight", type=_non_negative_float, default=0.10)
    bootstrap_market.add_argument("--minimum-instrument-price", type=_positive_decimal, default=Decimal("1"))
    bootstrap_market.add_argument("--maximum-instrument-price", type=_positive_decimal, default=Decimal("250"))
    bootstrap_market.add_argument("--funding-amount", type=_positive_decimal, default=Decimal("100000"))
    bootstrap_market.add_argument("--min-holders-per-instrument", type=_positive_int, default=5)
    bootstrap_market.add_argument("--max-positions-per-bot", type=_positive_int, default=500)
    bootstrap_market.add_argument("--random-seed", type=int, default=20260915)
    bootstrap_market.add_argument(
        "--ingest-data",
        action="store_true",
        help=(
            "ingest players, stats, social feeds, and the supplied market-value CSVs "
            "before bootstrap; players and stats run as jobs on the ingestion worker, "
            "which must be running"
        ),
    )
    bootstrap_market.add_argument(
        "--social-source-limit",
        type=_positive_int,
        default=100,
        help="maximum due social subscriptions to poll during ingestion, default: 100",
    )
    bootstrap_market.add_argument(
        "--social-lookback-hours",
        type=_positive_int,
        default=168,
        help="lookback used to aggregate bootstrap social signals, default: 168 (7 days)",
    )
    bootstrap_market.add_argument(
        "--worker-ingestion-timeout-minutes",
        type=_positive_int,
        default=30,
        help="how long to wait for each FBref job queued on the ingestion worker, default: 30",
    )
    bootstrap_market.add_argument("--league", type=int, default=9)
    bootstrap_market.add_argument(
        "--season", type=int, default=current_season(), help="season start year (2026 is 2026-27), default: the season in progress"
    )
    bootstrap_market.add_argument(
        "--market-values-dir",
        help="directory containing player_valuations.csv and players.csv for --ingest-data",
    )
    bootstrap_market.add_argument(
        "--commit",
        action="store_true",
        help="apply changes; without this flag the command is a read-only dry-run",
    )
    bootstrap_market.add_argument("--log-level", default="INFO")
    return parser

def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _positive_int_or_unlimited(value: str) -> int | None:
    if value.strip().casefold() in {"none", "unlimited"}:
        return None
    return _positive_int(value)


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite number")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative finite number")
    return parsed


def _positive_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal") from error
    if not parsed.is_finite() or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive finite decimal")
    return parsed


def _percentage(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal percentage") from error
    if not Decimal("0") < parsed < Decimal("100"):
        raise argparse.ArgumentTypeError("value must be greater than 0 and less than 100")
    return parsed


def _percentage_from_zero(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal percentage") from error
    if not Decimal("0") <= parsed < Decimal("100"):
        raise argparse.ArgumentTypeError("value must be at least 0 and less than 100")
    return parsed


def _percentage_up_to_100(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal percentage") from error
    if not Decimal("0") < parsed <= Decimal("100"):
        raise argparse.ArgumentTypeError("value must be greater than 0 and at most 100")
    return parsed
