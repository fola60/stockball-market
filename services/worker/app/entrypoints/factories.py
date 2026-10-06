"""Builders that wire services to their Postgres repositories and HTTP clients."""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from app.clients import HttpApiClient, HttpTradingEngineClient
from app.config import DatabaseSettings, FbrefIngestionSettings, Settings, TradingEngineSettings
from app.ingestion.betting_markets import (
    Bet365Client,
    BettingMarketIngestionService,
    PostgresBettingMarketRepository,
)
from app.ingestion.fbref import FbrefClient, PostgresFbrefRawPageRepository
from app.ingestion.fixtures import FixtureIngestionService, PostgresFixtureRepository
from app.ingestion.market_values import MarketValueImportService, PostgresMarketValueRepository
from app.ingestion.players import PlayerSeedService, PostgresPlayerRepository
from app.ingestion.social import (
    BlueskyConnector,
    MastodonConnector,
    PostgresSocialRepository,
    RssConnector,
    SocialIngestionService,
    SourceRegistry,
)
from app.ingestion.social.twitter import (
    PostgresTwitterInjuryRepository,
    TwitterInjuryIngestionService,
    TwitterRecentSearchClient,
)
from app.ingestion.stats import PlayerStatsIngestionService, PostgresPlayerStatsRepository
from app.jobs import IngestSocialSourceJobHandler
from app.league_roster import LeagueRosterService, PostgresLeagueRosterRepository
from app.match_freezes import (
    MatchFreezeService,
    MatchFreezeWindow,
    PostgresMatchFreezeRepository,
)
from app.seeding.dev_market import TradingEngineInstrumentSeeder
from app.synthetic_traders import (
    PostgresSyntheticTraderRepository,
    SyntheticTraderService,
    SyntheticTraderSpawner,
)


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def trading_engine_client(settings: Settings | TradingEngineSettings) -> HttpTradingEngineClient:
    return HttpTradingEngineClient(
        settings.trading_engine_url,
        timeout_seconds=settings.trading_engine_timeout_seconds,
    )


def fbref_settings(settings: Settings) -> FbrefIngestionSettings:
    return FbrefIngestionSettings(
        database_url=settings.database_url,
        base_url=settings.fbref_base_url,
        request_interval_seconds=settings.fbref_request_interval_seconds,
        user_agent=settings.fbref_user_agent,
        cache_ttl_seconds=settings.fbref_cache_ttl_seconds,
    )


def build_player_seed_service(settings: FbrefIngestionSettings) -> PlayerSeedService:
    return PlayerSeedService(
        client=build_fbref_client(settings),
        repository=PostgresPlayerRepository(settings.database_url),
    )


def build_fixture_ingestion_service(
    settings: FbrefIngestionSettings,
) -> FixtureIngestionService:
    return FixtureIngestionService(
        client=build_fbref_client(settings),
        repository=PostgresFixtureRepository(settings.database_url),
    )


def build_player_stats_ingestion_service(
    settings: FbrefIngestionSettings,
) -> PlayerStatsIngestionService:
    return PlayerStatsIngestionService(
        client=build_fbref_client(settings),
        repository=PostgresPlayerStatsRepository(settings.database_url),
    )


def build_market_value_import_service(
    settings: DatabaseSettings | Settings,
) -> MarketValueImportService:
    return MarketValueImportService(
        repository=PostgresMarketValueRepository(settings.database_url),
    )


def build_bet365_ingestion_service(
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


def build_twitter_injury_ingestion_service(settings: Settings) -> TwitterInjuryIngestionService:
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


def build_social_source_handler(
    repository: PostgresSocialRepository,
) -> IngestSocialSourceJobHandler:
    return IngestSocialSourceJobHandler(
        social_ingestion_service=SocialIngestionService(
            repository,
            SourceRegistry((BlueskyConnector(), RssConnector(), MastodonConnector())),
        ),
        repository=repository,
    )


def build_match_freeze_service(settings: Settings) -> MatchFreezeService:
    return MatchFreezeService(
        repository=PostgresMatchFreezeRepository(settings.database_url),
        engine=trading_engine_client(settings),
        window=MatchFreezeWindow(
            lineup_lock=timedelta(minutes=settings.match_freeze_lineup_lock_minutes),
            settlement=timedelta(minutes=settings.match_freeze_settlement_minutes),
        ),
    )


def build_synthetic_trader_service(settings: Settings) -> SyntheticTraderService:
    return SyntheticTraderService(
        repository=PostgresSyntheticTraderRepository(
            settings.database_url,
            social_signals_enabled=settings.social_signals_enabled,
            social_signal_max_age_seconds=settings.social_signal_max_age_seconds,
        ),
        trading_engine_client=trading_engine_client(settings),
    )


def build_synthetic_trader_spawner(settings: Settings) -> SyntheticTraderSpawner:
    return SyntheticTraderSpawner(
        api_client=HttpApiClient(
            settings.api_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        ),
        repository=PostgresSyntheticTraderRepository(settings.database_url),
    )


def build_fbref_client(settings: FbrefIngestionSettings) -> FbrefClient:
    return FbrefClient(
        base_url=settings.base_url,
        request_interval_seconds=settings.request_interval_seconds,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        page_cache=PostgresFbrefRawPageRepository(settings.database_url),
    )


def build_league_roster_service(
    settings: Settings, fbref: FbrefIngestionSettings
) -> LeagueRosterService:
    engine = trading_engine_client(settings)
    return LeagueRosterService(
        repository=PostgresLeagueRosterRepository(settings.database_url),
        engine=engine,
        players=build_player_seed_service(fbref),
        instruments=TradingEngineInstrumentSeeder(engine),
    )


def build_fotmob_ingestion_service(settings, *, archive_dir=None):
    from app.ingestion.fotmob import FotMobClient, FotMobIngestionService, FotMobRepository

    interval = getattr(settings, "fotmob_request_interval_seconds", None)
    if interval is None:
        interval = float(os.getenv("STOCKBALL_FOTMOB_REQUEST_INTERVAL_SECONDS", "2"))
    return FotMobIngestionService(
        FotMobClient(interval_seconds=interval, archive_dir=archive_dir),
        FotMobRepository(settings.database_url),
    )
