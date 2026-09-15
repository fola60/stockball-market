from __future__ import annotations

from uuid import UUID

from app.portfolios.models import PortfolioActivityRecord, PortfolioRecord
from app.portfolios.repository import PortfoliosRepository


class PortfolioNotFoundError(Exception):
    def __init__(self, portfolio_id: UUID) -> None:
        self.portfolio_id = portfolio_id
        super().__init__(f"portfolio {portfolio_id} was not found")


class PortfoliosService:
    def __init__(self, repository: PortfoliosRepository) -> None:
        self._repository = repository

    def get_portfolio(self, portfolio_id: UUID) -> PortfolioRecord:
        portfolio = self._repository.get_portfolio(portfolio_id)
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)
        return portfolio

    def list_activity(self, portfolio_id: UUID, limit: int) -> list[PortfolioActivityRecord]:
        self.get_portfolio(portfolio_id)
        return self._repository.list_activity(portfolio_id, limit)
