from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.traders.models import (
    LeaderboardFilter,
    LeaderboardPage,
    TraderHoldingRecord,
    TraderKind,
    TraderProfileRecord,
    TraderStandingRecord,
    TraderTradeRecord,
)
from app.traders.service import TradersService

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _standing(rank: int, kind: TraderKind = TraderKind.PERSON) -> TraderStandingRecord:
    return TraderStandingRecord(
        account_id=UUID(int=rank),
        display_name=f"Trader {rank}",
        kind=kind,
        rank=rank,
        net_worth="150000.0000",
        cash_balance="50000.0000",
        holdings_value="100000.0000",
        holdings_count=3,
        joined_at=NOW,
    )


class FakeTradersRepository:
    def __init__(self) -> None:
        self.leaderboard_calls: list[tuple[LeaderboardFilter, int, int]] = []
        self.profiles: dict[UUID, TraderProfileRecord] = {}

    def leaderboard(self, filter_, limit, offset) -> LeaderboardPage:
        self.leaderboard_calls.append((filter_, limit, offset))
        entries = [_standing(1), _standing(2, TraderKind.BOT)]
        return LeaderboardPage(entries=entries, total=2, limit=limit, offset=offset)

    def profile(self, account_id, trade_limit):
        return self.profiles.get(account_id)


class TradersApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeTradersRepository()
        self.client = TestClient(
            create_app(
                instruments_service=object(),  # type: ignore[arg-type]
                traders_service=TradersService(self.repository),
            )
        )

    def test_leaderboard_lists_ranked_traders_without_private_fields(self) -> None:
        response = self.client.get("/v1/traders/leaderboard", params={"filter": "PEOPLE"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual([entry["rank"] for entry in body["entries"]], [1, 2])
        self.assertEqual(body["entries"][1]["kind"], "BOT")
        for private_field in ("email", "handle"):
            self.assertNotIn(private_field, body["entries"][0])
        self.assertEqual(self.repository.leaderboard_calls, [(LeaderboardFilter.PEOPLE, 50, 0)])

    def test_leaderboard_rejects_oversized_pages(self) -> None:
        response = self.client.get("/v1/traders/leaderboard", params={"limit": 101})

        self.assertEqual(response.status_code, 422)

    def test_service_clamps_page_bounds(self) -> None:
        service = TradersService(self.repository)

        service.leaderboard(limit=1000, offset=-5)

        self.assertEqual(self.repository.leaderboard_calls[-1], (LeaderboardFilter.ALL, 100, 0))

    def test_profile_returns_holdings_and_recent_trades(self) -> None:
        account_id = UUID(int=1)
        instrument_id = uuid4()
        self.repository.profiles[account_id] = TraderProfileRecord(
            standing=_standing(1),
            holdings=[
                TraderHoldingRecord(
                    instrument_id=instrument_id,
                    symbol="SAKA",
                    player_name="Bukayo Saka",
                    player_club="Arsenal",
                    player_position="FW",
                    quantity="10",
                    current_price="146.7500",
                    market_value="1467.5000",
                    price_change_24h="0.5000",
                )
            ],
            recent_trades=[
                TraderTradeRecord(
                    trade_id=uuid4(),
                    instrument_id=instrument_id,
                    player_name="Bukayo Saka",
                    side="BUY",
                    shares="10",
                    execution_price="146.0000",
                    gross_amount="1460.0000",
                    executed_at=NOW,
                )
            ],
        )

        response = self.client.get(f"/v1/traders/{account_id}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["trader"]["display_name"], "Trader 1")
        self.assertEqual(body["holdings"][0]["player_name"], "Bukayo Saka")
        self.assertEqual(body["recent_trades"][0]["side"], "BUY")

    def test_unknown_trader_is_404(self) -> None:
        response = self.client.get(f"/v1/traders/{uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "trader_not_found")


if __name__ == "__main__":
    unittest.main()
