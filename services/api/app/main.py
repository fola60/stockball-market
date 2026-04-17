from __future__ import annotations

from fastapi import FastAPI

from app.accounts.repository import PostgresAccountsRepository
from app.accounts.router import router as accounts_router
from app.accounts.service import AccountsService
from app.config import Settings


def create_app(accounts_service: AccountsService | None = None) -> FastAPI:
    app = FastAPI(title="Stockball API", version="0.1.0")

    if accounts_service is None:
        settings = Settings.from_env()
        accounts_service = AccountsService(
            repository=PostgresAccountsRepository(settings.database_url)
        )

    app.state.accounts_service = accounts_service
    app.include_router(accounts_router)

    @app.get("/healthz", tags=["health"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app
