"""One-off CLI commands that pull external football data into Postgres."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

from app.config import DatabaseSettings, FbrefIngestionSettings, Settings
from app.entrypoints.factories import (
    build_bet365_ingestion_service,
    build_fixture_ingestion_service,
    build_market_value_import_service,
    build_player_seed_service,
    build_player_stats_ingestion_service,
    build_twitter_injury_ingestion_service,
    configure_logging,
)
from app.ingestion.betting_markets import Bet365IngestionError
from app.ingestion.fbref import FbrefAccessDeniedError
from app.ingestion.social.twitter import (
    PostgresTwitterInjuryRepository,
    TwitterIngestionError,
    load_registry,
)
from app.jobs import Bet365IngestionMode

logger = logging.getLogger(__name__)


def seed_players(args) -> int:
    settings = FbrefIngestionSettings.from_env()
    configure_logging(args.log_level)
    try:
        result = build_player_seed_service(settings).seed_players(args.league, args.season)
    except FbrefAccessDeniedError as error:
        print_provider_access_error(error)
        return 1
    logger.info(
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


def ingest_fixtures(args) -> int:
    settings = FbrefIngestionSettings.from_env()
    configure_logging(args.log_level)
    try:
        result = build_fixture_ingestion_service(settings).ingest_fixtures(
            league=args.league,
            season=args.season,
            from_date=_optional_date_arg(args.from_date),
            to_date=_optional_date_arg(args.to_date),
        )
    except FbrefAccessDeniedError as error:
        print_provider_access_error(error)
        return 1
    print(
        f"upserted {result.upserted_fixtures} fixtures "
        f"for league {args.league} season {args.season}"
    )
    return 0


def ingest_player_stats(args) -> int:
    settings = FbrefIngestionSettings.from_env()
    configure_logging(args.log_level)
    try:
        result = build_player_stats_ingestion_service(settings).ingest_player_stats(
            league=args.league,
            season=args.season,
            stat_types=tuple(args.stat_type) if args.stat_type else None,
        )
    except FbrefAccessDeniedError as error:
        print_provider_access_error(error)
        return 1
    print(
        f"upserted {result.upserted_observations} player-stat observations "
        f"for league {args.league} season {args.season}; "
        f"matched {result.matched_players} players"
    )
    return 0


def import_market_values(args) -> int:
    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    result = build_market_value_import_service(settings).import_transfermarkt_csv(
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


def ingest_bet365_odds(args) -> int:
    settings = Settings.from_env()
    configure_logging(args.log_level)
    try:
        service = build_bet365_ingestion_service(
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


def sync_twitter_injury_registry(args) -> int:
    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    repository = PostgresTwitterInjuryRepository(settings.database_url)
    result = repository.sync_registry(load_registry(Path(args.registry)))
    print(
        f"synced {result.source_accounts} X source accounts and "
        f"{result.player_aliases} player aliases"
    )
    return 0


def ingest_twitter_injuries(args) -> int:
    settings = Settings.from_env()
    configure_logging(args.log_level)
    query = args.query or settings.twitter_search_query
    if not query:
        print(
            "Twitter injury ingestion unavailable: set STOCKBALL_TWITTER_SEARCH_QUERY "
            "or pass --query"
        )
        return 1
    try:
        result = build_twitter_injury_ingestion_service(settings).ingest_recent(
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


def print_provider_access_error(error: FbrefAccessDeniedError) -> None:
    logger.error("FBref ingestion access denied", extra={"error": str(error)})
    print("FBref denied this ingestion request. ")


def _optional_date_arg(raw_value: str | None) -> date | None:
    if raw_value is None:
        return None
    return date.fromisoformat(raw_value)


def ingest_fotmob_ratings(args) -> int:
    import json

    from app.entrypoints.factories import build_fotmob_ingestion_service
    from app.seasons import resolve_season

    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    service = build_fotmob_ingestion_service(
        settings, archive_dir=Path(args.archive_dir) if args.archive_dir else None,
    )
    result = service.ingest(league=args.league, season=resolve_season(args.season),
                            backfill=args.backfill, refresh=args.refresh, limit=args.max_matches)
    print(json.dumps(result, sort_keys=True))
    return 1 if result['failed_matches'] else 0


def ingest_fotmob_images(args) -> int:
    import json

    from app.entrypoints.factories import build_fotmob_ingestion_service

    settings = DatabaseSettings.from_env()
    configure_logging(args.log_level)
    result = build_fotmob_ingestion_service(settings).ingest_images(limit=args.max_images)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["failed"] else 0
