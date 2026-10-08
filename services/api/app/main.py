from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.accounts.repository import PostgresAccountsRepository
from app.accounts.router import router as accounts_router
from app.accounts.service import AccountsService
from app.admin import AdminService
from app.admin.environment import EnvironmentFileService
from app.admin.processes import RedisProcessRegistry
from app.admin.repository import PostgresAdminRepository
from app.admin.router import router as admin_router
from app.admin.runtime_settings import RuntimeSettingsRegistry
from app.admin.service import RedisJobPublisher
from app.auth.repository import PostgresAuthRepository
from app.auth.router import router as auth_router
from app.auth.service import AuthService
from app.clients.trading_engine import HttpTradingEngineClient
from app.config import Settings
from app.instruments.repository import PostgresInstrumentsRepository
from app.instruments.router import router as instruments_router
from app.instruments.service import InstrumentsService
from app.market.repository import PostgresMarketRepository
from app.market.router import router as market_router
from app.market.service import MarketService
from app.orders.router import router as orders_router
from app.orders.service import OrdersService
from app.portfolios.repository import PostgresPortfoliosRepository
from app.portfolios.router import router as portfolios_router
from app.portfolios.service import PortfoliosService
from app.request_telemetry import RequestTelemetry, RequestTelemetryMiddleware
from app.traders.repository import PostgresTradersRepository
from app.traders.router import router as traders_router
from app.traders.service import TradersService


def create_app(
    accounts_service: AccountsService | None = None,
    instruments_service: InstrumentsService | None = None,
    portfolios_service: PortfoliosService | None = None,
    orders_service: OrdersService | None = None,
    auth_service: AuthService | None = None,
    admin_service: AdminService | None = None,
    traders_service: TradersService | None = None,
    market_service: MarketService | None = None,
) -> FastAPI:
    app = FastAPI(title="Stockball API", version="0.1.0")
    request_telemetry = RequestTelemetry()

    if all(
        service is None
        for service in (
            accounts_service,
            instruments_service,
            portfolios_service,
            orders_service,
        )
    ):
        settings = Settings.from_env()
        accounts_service = AccountsService(
            repository=PostgresAccountsRepository(settings.database_url)
        )
        instruments_service = InstrumentsService(
            repository=PostgresInstrumentsRepository(settings.database_url)
        )
        portfolios_service = PortfoliosService(
            repository=PostgresPortfoliosRepository(settings.database_url)
        )
        traders_service = TradersService(PostgresTradersRepository(settings.database_url))
        market_service = MarketService(
            PostgresMarketRepository(settings.database_url),
            lineup_lock_minutes=settings.lineup_lock_minutes,
        )
        trading_engine_client = HttpTradingEngineClient(
            settings.trading_engine_url,
            timeout_seconds=settings.trading_engine_timeout_seconds,
        )
        orders_service = OrdersService(trading_engine_client=trading_engine_client)
        auth_service = AuthService(
            PostgresAuthRepository(settings.database_url),
            trading_engine=trading_engine_client,
            opening_balance=settings.user_opening_balance,
        )
        if settings.admin_api_enabled:
            repository = PostgresAdminRepository(settings.database_url)
            admin_service = AdminService(
                repository=repository,
                publisher=RedisJobPublisher(
                    settings.redis_url,
                    settings.ingestion_queue_name,
                    {
                        "APPLY_TOPUPS": settings.trading_queue_name,
                        "SYNTHETIC_TRADER_TICK": settings.trading_queue_name,
                        "CHECK_MARKET_FREEZES": settings.trading_queue_name,
                    },
                ),
                process_registry=RedisProcessRegistry(
                    settings.redis_url,
                    (
                        settings.trading_queue_name,
                        settings.ingestion_queue_name,
                    ),
                    executable_run_ids=repository.executable_run_ids,
                    runtime_values=repository.runtime_setting_values,
                ),
                runtime_settings=RuntimeSettingsRegistry(repository),
            )
            env_path = Path(os.getenv("STOCKBALL_ENV_FILE_PATH", "/config/stockball.env"))
            example_path = Path(os.getenv("STOCKBALL_ENV_EXAMPLE_PATH", "/config/stockball.env.example"))
            if env_path.exists() and example_path.exists():
                app.state.environment_service = EnvironmentFileService(
                    env_path,
                    example_path,
                    repository,
                    admin_service.runtime_settings,
                )

    app.state.accounts_service = accounts_service
    app.state.instruments_service = instruments_service
    app.state.portfolios_service = portfolios_service
    app.state.orders_service = orders_service
    app.state.auth_service = auth_service
    app.state.admin_service = admin_service
    app.state.traders_service = traders_service
    app.state.market_service = market_service
    if not hasattr(app.state, "environment_service"):
        app.state.environment_service = None
    app.state.request_telemetry = request_telemetry
    app.add_middleware(RequestTelemetryMiddleware, telemetry=request_telemetry)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(accounts_router)
    app.include_router(auth_router)
    app.include_router(instruments_router)
    app.include_router(portfolios_router)
    app.include_router(orders_router)
    app.include_router(traders_router)
    app.include_router(market_router)
    app.include_router(admin_router)

    @app.get("/healthz", tags=["health"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app
