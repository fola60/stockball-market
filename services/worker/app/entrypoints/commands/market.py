"""One-off CLI commands that set up the market: instruments, the bot fleet, and seeding."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2

from app.clients import (
    ApiClientError,
    ApiUnavailableError,
    RecalibratePriceCurvesCommand,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)
from app.config import Settings, TradingEngineSettings
from app.entrypoints.factories import (
    build_market_value_import_service,
    build_social_source_handler,
    build_synthetic_trader_spawner,
    configure_logging,
    trading_engine_client,
)
from app.ingestion.social import PostgresSocialRepository, SocialSignalAggregationService
from app.jobs import (
    IngestPlayersJobPayload,
    IngestPlayerStatsJobPayload,
    IngestSocialSourceJobPayload,
    RetryableJobError,
    WorkerJob,
)
from app.league_roster import LeagueRosterService, PostgresLeagueRosterRepository
from app.queue import RedisJobQueue
from app.seeding import (
    BootstrapAllocationError,
    PostgresSyntheticPortfolioBootstrapRepository,
    SyntheticPortfolioBootstrapService,
)
from app.seeding.dev_market import (
    DevMarketBootstrapError,
    DevMarketBootstrapOptions,
    DevMarketBootstrapService,
    FleetPlanningOptions,
    PostgresDevMarketBootstrapRepository,
    SyntheticFleetFundService,
    SyntheticPortfolioInitializer,
    TradingEngineInstrumentSeeder,
    ValuationOptions,
)
from app.seeding.worker_jobs import PostgresJobRunStore, WorkerJobDispatcher, WorkerJobFailedError
from app.synthetic_traders import (
    BotStatus,
    SpawnNameStyle,
    SpawnSyntheticTraderCommand,
    StrategyEngine,
    SyntheticTraderConfigNotFoundError,
)
from app.topups import PostgresTopupRepository, TopupService


def seed_player_shares(args) -> int:
    settings = Settings.from_env()
    configure_logging(args.log_level)
    result = trading_engine_client(settings).seed_player_shares()
    print(
        f"seeded player shares: {result.created_count} created, "
        f"{result.skipped_existing_count} skipped existing, "
        f"{result.market_value_priced_count} market-value priced, "
        f"{result.fallback_priced_count} fallback priced"
    )
    return 0


def recalibrate_price_curves(args) -> int:
    settings = Settings.from_env()
    configure_logging(args.log_level)
    request_id = args.request_id or (
        f"price-curves:{datetime.now(UTC).date().isoformat()}:"
        f"{args.multiplier}x:{args.depth_divisor}"
    )
    try:
        result = trading_engine_client(settings).recalibrate_price_curves(
            RecalibratePriceCurvesCommand(
                request_id=request_id,
                full_supply_price_multiplier=args.multiplier,
                curve_depth_divisor=args.depth_divisor,
                reason=args.reason,
                dry_run=not args.apply,
            )
        )
    except TradingEngineClientError as error:
        details = error.body.get("details")
        print(f"price curve recalibration failed: {error}" + (f" {details}" if details else ""))
        return 1
    except TradingEngineUnavailableError as error:
        print(f"price curve recalibration failed: {error}")
        return 1
    verb = "would rebase" if result.dry_run else "rebased"
    print(
        f"{verb} {result.instrument_count} price curves to {result.full_supply_price_multiplier}x "
        f"over 1/{result.curve_depth_divisor} of supply (request {result.request_id}); "
        f"{result.reset_net_demand_count} carried net demand, largest "
        f"{float(result.max_reset_demand_ratio):.2%} of its old curve; previous multipliers "
        f"{result.previous_min_multiplier}-{result.previous_max_multiplier}. Prices are unchanged."
    )
    if result.dry_run:
        print("dry run: nothing was written; rerun with --apply to rebase")
    return 0


def spawn_synthetic_traders(args) -> int:
    settings = Settings.from_env()
    configure_logging(args.log_level)
    try:
        result = build_synthetic_trader_spawner(settings).spawn(
            SpawnSyntheticTraderCommand(
                count=args.count,
                handle_prefix=args.handle_prefix,
                display_name_prefix=args.display_name_prefix,
                config_key=args.config_key,
                strategy_engine=(
                    None if args.strategy_engine is None else StrategyEngine(args.strategy_engine)
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


def bootstrap_synthetic_portfolios(args) -> int:
    settings = TradingEngineSettings.from_env()
    configure_logging(args.log_level)
    try:
        result = SyntheticPortfolioBootstrapService(
            PostgresSyntheticPortfolioBootstrapRepository(
                settings.database_url, trading_engine_client(settings)
            )
        ).bootstrap(
            bot_ids=tuple(args.bot_id or ()),
            all_active_synthetic_bots=args.all_active_synthetic_bots,
            seed=args.seed,
            min_holders_per_player=args.min_holders_per_player,
            max_player_supply_per_bot=args.max_player_supply_per_bot,
            reserve_supply_percent=args.reserve_supply_percent,
            max_positions_per_bot=args.max_positions_per_bot,
            top_player_holder_percent=args.top_player_holder_percent,
            holder_price_exponent=args.holder_price_exponent,
            target_seed_value_per_bot=args.target_seed_value_per_bot,
            seed_value_jitter_percent=args.seed_value_jitter_percent,
            risk_limit_headroom_percent=args.risk_limit_headroom_percent,
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
    print(f"bot distribution: {result.bot_distribution()}")
    print(f"holders by price quintile: {result.holders_by_price_quintile()}")
    for symbol, reason in result.skipped_instruments:
        print(f"skipped {symbol}: {reason}")
    return 0


def bootstrap_dev_market(args) -> int:
    settings = Settings.from_env()
    configure_logging(args.log_level)
    if args.ingest_data and not args.commit:
        print("--ingest-data requires --commit because ingestion mutates persistent data")
        return 1
    try:
        if args.ingest_data:
            _ingest_bootstrap_data(settings, args)
        engine = trading_engine_client(settings)
        topup_repository = PostgresTopupRepository(settings.database_url)
        report = DevMarketBootstrapService(
            repository=PostgresDevMarketBootstrapRepository(settings.database_url, engine),
            instrument_seeder=TradingEngineInstrumentSeeder(engine),
            spawner=build_synthetic_trader_spawner(settings),
            funder=SyntheticFleetFundService(
                topup_repository,
                TopupService(
                    trading_engine_client=engine,
                    policy_store=topup_repository,
                    audit_store=topup_repository,
                ),
            ),
            portfolio_bootstrapper=SyntheticPortfolioInitializer(
                SyntheticPortfolioBootstrapService(
                    PostgresSyntheticPortfolioBootstrapRepository(settings.database_url, engine)
                )
            ),
            roster=LeagueRosterService(
                repository=PostgresLeagueRosterRepository(settings.database_url), engine=engine
            ),
        ).run(
            DevMarketBootstrapOptions(
                fleet=FleetPlanningOptions(
                    target_trades_per_hour_per_instrument=(
                        args.target_trades_per_hour_per_instrument
                    ),
                    max_bots=args.max_bots,
                    popularity_headroom=args.popularity_headroom,
                ),
                valuation=ValuationOptions(
                    market_value_weight=args.market_value_weight,
                    stats_weight=args.stats_weight,
                    social_weight=args.social_weight,
                    minimum_price=args.minimum_instrument_price,
                    maximum_price=args.maximum_instrument_price,
                ),
                seed=args.random_seed,
                funding_amount=args.funding_amount,
                min_holders_per_instrument=args.min_holders_per_instrument,
                max_positions_per_bot=args.max_positions_per_bot,
                commit=args.commit,
                season=args.season,
            )
        )
    except (
        ApiClientError,
        ApiUnavailableError,
        BootstrapAllocationError,
        DevMarketBootstrapError,
        psycopg2.Error,
        TradingEngineClientError,
        TradingEngineUnavailableError,
        WorkerJobFailedError,
    ) as error:
        print(f"development market bootstrap failed: {error}")
        return 1
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


def _ingest_bootstrap_data(settings: Settings, args) -> None:
    # FBref is challenged from this short-lived container but not from the long-running
    # ingestion worker, so players and stats are queued there and awaited.
    dispatcher = WorkerJobDispatcher(
        PostgresJobRunStore(settings.database_url),
        RedisJobQueue(settings.redis_url, settings.ingestion_queue_name),
    )
    timeout = timedelta(minutes=args.worker_ingestion_timeout_minutes)
    players = dispatcher.run(
        "INGEST_PLAYERS",
        WorkerJob.ingest_players(IngestPlayersJobPayload(league=args.league, season=args.season)),
        timeout,
    )
    print(f"ingested {players.successful_items} players (worker run {players.run_id})")
    stats = dispatcher.run(
        "INGEST_PLAYER_STATS",
        WorkerJob.ingest_player_stats(
            IngestPlayerStatsJobPayload(league=args.league, season=args.season)
        ),
        timeout,
    )
    print(
        f"ingested {stats.successful_items} player-stat observations "
        f"(worker run {stats.run_id})"
    )
    if args.market_values_dir:
        market_values_dir = Path(args.market_values_dir)
        valuations = market_values_dir / "player_valuations.csv"
        player_profiles = market_values_dir / "players.csv"
        if not valuations.is_file():
            raise DevMarketBootstrapError(f"market-value CSV not found: {valuations}")
        result = build_market_value_import_service(settings).import_transfermarkt_csv(
            valuations_csv_path=valuations,
            players_csv_path=player_profiles if player_profiles.is_file() else None,
            source="transfermarkt_csv",
            currency="EUR",
        )
        print(f"imported {result.matched_rows} matched market values")
    _ingest_bootstrap_social_data(
        settings,
        source_limit=args.social_source_limit,
        lookback=timedelta(hours=args.social_lookback_hours),
    )


def _ingest_bootstrap_social_data(
    settings: Settings,
    *,
    source_limit: int,
    lookback: timedelta,
) -> None:
    repository = PostgresSocialRepository(settings.database_url)
    source_handler = build_social_source_handler(repository)
    subscription_ids = repository.list_due_subscriptions(
        datetime.now(UTC),
        limit=source_limit,
    )
    fetched = 0
    inserted = 0
    processed = 0
    failed = 0
    for subscription_id in subscription_ids:
        try:
            result = source_handler.handle(
                WorkerJob.ingest_social_source(
                    IngestSocialSourceJobPayload(subscription_id=subscription_id)
                )
            )
        except RetryableJobError:
            failed += 1
            continue
        fetched += int(result.metrics.get("fetched_documents", 0))
        inserted += result.successful_items
        processed += int(result.metrics.get("immediate_documents_processed", 0))
        failed += result.failed_items
    signals = SocialSignalAggregationService(repository).aggregate(lookback)
    print(
        "ingested social feeds: "
        f"{len(subscription_ids)} subscriptions polled, "
        f"{fetched} documents fetched, {inserted} inserted, "
        f"{processed} processed, {failed} source failures, "
        f"{signals.snapshots_written} player signals aggregated"
    )
