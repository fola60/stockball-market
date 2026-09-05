from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.accounts.repository import PostgresAccountsRepository
from app.accounts.router import router as accounts_router
from app.accounts.service import AccountsService
from app.clients.trading_engine import HttpTradingEngineClient
from app.config import Settings
from app.dev_operations import DevOperationsService
from app.dev_operations.repository import PostgresDevOperationsRepository
from app.dev_operations.router import router as dev_operations_router
from app.dev_operations.service import RedisJobPublisher
from app.dev_operations.processes import RedisProcessRegistry
from app.instruments.repository import PostgresInstrumentsRepository
from app.instruments.router import router as instruments_router
from app.instruments.service import InstrumentsService
from app.orders.router import router as orders_router
from app.orders.service import OrdersService
from app.portfolios.repository import PostgresPortfoliosRepository
from app.portfolios.router import router as portfolios_router
from app.portfolios.service import PortfoliosService


def create_app(
    accounts_service: AccountsService | None = None,
    instruments_service: InstrumentsService | None = None,
    portfolios_service: PortfoliosService | None = None,
    orders_service: OrdersService | None = None,
    dev_operations_service: DevOperationsService | None = None,
) -> FastAPI:
    app = FastAPI(title="Stockball API", version="0.1.0")

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
        orders_service = OrdersService(
            trading_engine_client=HttpTradingEngineClient(
                settings.trading_engine_url,
                timeout_seconds=settings.trading_engine_timeout_seconds,
            )
        )
        if settings.dev_portal_enabled:
            repository = PostgresDevOperationsRepository(settings.database_url)
            dev_operations_service = DevOperationsService(
                repository=repository,
                publisher=RedisJobPublisher(settings.redis_url, settings.queue_name),
                process_registry=RedisProcessRegistry(settings.redis_url, settings.queue_name),
            )

    app.state.accounts_service = accounts_service
    app.state.instruments_service = instruments_service
    app.state.portfolios_service = portfolios_service
    app.state.orders_service = orders_service
    app.state.dev_operations_service = dev_operations_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(accounts_router)
    app.include_router(instruments_router)
    app.include_router(portfolios_router)
    app.include_router(orders_router)
    app.include_router(dev_operations_router)

    @app.get("/healthz", tags=["health"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app
