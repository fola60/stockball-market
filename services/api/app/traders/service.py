from __future__ import annotations

from uuid import UUID

from app.traders.models import LeaderboardFilter, LeaderboardPage, TraderProfileRecord
from app.traders.repository import TradersRepository

MAX_PAGE_SIZE = 100
PROFILE_TRADE_LIMIT = 20


class TraderNotFoundError(Exception):
    def __init__(self, account_id: UUID) -> None:
        self.account_id = account_id
        super().__init__(f"trader {account_id} was not found")


class TradersService:
    """Public standings: who is richest, and what each trader holds.

    Only display names, holdings, and trades are exposed. Emails, handles, and admin or
    system accounts never are.
    """

    def __init__(self, repository: TradersRepository) -> None:
        self._repository = repository

    def leaderboard(
        self, filter_: LeaderboardFilter = LeaderboardFilter.ALL, limit: int = 50, offset: int = 0
    ) -> LeaderboardPage:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        return self._repository.leaderboard(filter_, limit, max(0, offset))

    def profile(self, account_id: UUID) -> TraderProfileRecord:
        profile = self._repository.profile(account_id, PROFILE_TRADE_LIMIT)
        if profile is None:
            raise TraderNotFoundError(account_id)
        return profile
