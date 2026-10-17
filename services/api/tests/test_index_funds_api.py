from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.index_funds.models import (
    BasketChangePlayerRecord,
    BasketChangeRecord,
    IndexConstituentRecord,
    IndexFundRecord,
)
from app.index_funds.service import IndexFundsService, squad_profile
from app.instruments.models import (
    InstrumentStatus,
    PlayerStatsRecord,
    RadarAxisRecord,
    RadarMetricRecord,
)
from app.instruments.service import InstrumentsService
from app.main import create_app


def _constituent(price: str, position: str = "FW") -> IndexConstituentRecord:
    return IndexConstituentRecord(
        instrument_id=uuid4(),
        symbol=f"SYM-{price}",
        player_name=f"Player {price}",
        player_position=position,
        status=InstrumentStatus.ACTIVE,
        shares_per_unit="1",
        current_price=price,
        weight="0",
        price_change_24h="0",
        player_image_version=None,
    )


def _axis(label: str, score: int) -> RadarAxisRecord:
    return RadarAxisRecord(
        label=label,
        score=score,
        value="1 metrics",
        components=[RadarMetricRecord(label=f"{label} metric", score=score, value="x")],
    )


def _stats(group: str, axes: list[RadarAxisRecord]) -> PlayerStatsRecord:
    return PlayerStatsRecord(
        season=2026,
        games=8,
        starts=8,
        minutes=720,
        goals=1,
        assists=1,
        shots=10,
        shots_on_target=5,
        yellow_cards=0,
        red_cards=0,
        comparison_group=group,
        comparison_size=40,
        radar_axes=axes,
    )


def _fund(fund_id: UUID) -> IndexFundRecord:
    now = datetime(2026, 10, 16, tzinfo=UTC)
    return IndexFundRecord(
        id=fund_id,
        symbol="IDX-ARS",
        display_name="Arsenal Index",
        index_kind="TEAM",
        club="Arsenal",
        current_price="100.000000000000",
        cash_per_unit="2.5",
        status=InstrumentStatus.FROZEN,
        freeze_reason="MATCH_DAY",
        constituent_count=3,
        units_outstanding="2.5",
        price_change_24h="1.2500",
        price_change_7d="-0.5000",
        volume_24h="2.5",
        traded_value_24h="250.0000",
        club_badge_version=None,
        created_at=now,
        updated_at=now,
    )


class FakeInstrumentsRepository:
    """Only the stats lookup the fund profile needs."""

    def __init__(self, player_stats: dict[UUID, PlayerStatsRecord]) -> None:
        self._player_stats = player_stats

    def list_player_stats(self, instrument_ids: list[UUID]) -> dict[UUID, PlayerStatsRecord]:
        return {id: self._player_stats[id] for id in instrument_ids if id in self._player_stats}


class FakeIndexFundsRepository:
    def __init__(self, fund: IndexFundRecord, constituents: list[IndexConstituentRecord]):
        self.fund = fund
        self.constituents = constituents

    def list_index_funds(self) -> list[IndexFundRecord]:
        return [self.fund]

    def get_index_fund(self, instrument_id: UUID) -> IndexFundRecord | None:
        return self.fund if instrument_id == self.fund.id else None

    def list_constituents(self, instrument_id: UUID) -> list[IndexConstituentRecord]:
        return self.constituents

    def list_basket_changes(self, instrument_id: UUID, limit: int) -> list[BasketChangeRecord]:
        return [
            BasketChangeRecord(
                kind="DELISTING",
                reason="left the league",
                added=[],
                removed=[BasketChangePlayerRecord(uuid4(), "Departed Player")],
                unit_price_before="100",
                unit_price_after="100",
                created_at=datetime(2026, 10, 17, tzinfo=UTC),
            )
        ][:limit]


class SquadProfileTests(unittest.TestCase):
    def test_axes_weight_players_by_unit_value_over_the_players_they_apply_to(self) -> None:
        striker = _constituent("60", "FW")
        midfielder = _constituent("20", "MF")
        keeper = _constituent("20", "GK")
        stats = {
            striker.instrument_id: _stats(
                "FW", [_axis("Shooting", 90), _axis("Availability", 40)]
            ),
            midfielder.instrument_id: _stats(
                "MF", [_axis("Shooting", 30), _axis("Availability", 80)]
            ),
            keeper.instrument_id: _stats(
                "GK", [_axis("Shot stopping", 70), _axis("Availability", 100)]
            ),
        }

        profile = squad_profile([striker, midfielder, keeper], stats)

        assert profile is not None
        axes = {axis.label: axis for axis in profile.radar_axes}
        # (60 x 90 + 20 x 30) / 80
        self.assertEqual(axes["Shooting"].score, 75)
        self.assertEqual(axes["Shooting"].value, "2 players")
        self.assertEqual(axes["Shot stopping"].score, 70)
        self.assertEqual(axes["Shot stopping"].value, "1 player")
        # (60 x 40 + 20 x 80 + 20 x 100) / 100
        self.assertEqual(axes["Availability"].score, 60)
        self.assertEqual(axes["Availability"].components[0].score, 60)
        self.assertEqual(
            [axis.label for axis in profile.radar_axes],
            ["Shooting", "Shot stopping", "Availability"],
        )
        self.assertEqual(profile.comparison_size, 3)

    def test_no_profile_without_stats(self) -> None:
        self.assertIsNone(squad_profile([_constituent("10")], {}))


class IndexFundsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fund_id = uuid4()
        self.constituents = [_constituent("60"), _constituent("40")]
        instruments = FakeInstrumentsRepository(
            {self.constituents[0].instrument_id: _stats("FW", [_axis("Shooting", 80)])}
        )
        app = create_app(
            instruments_service=InstrumentsService(instruments),
            index_funds_service=IndexFundsService(
                FakeIndexFundsRepository(_fund(self.fund_id), self.constituents),
                instruments,
            ),
        )
        self.client = TestClient(app)

    def test_lists_funds(self) -> None:
        response = self.client.get("/v1/index-funds")

        self.assertEqual(response.status_code, 200)
        (fund,) = response.json()
        self.assertEqual(fund["symbol"], "IDX-ARS")
        self.assertEqual(fund["status"], "FROZEN")
        self.assertEqual(fund["freeze_reason"], "MATCH_DAY")

    def test_fund_detail_includes_basket_and_profile(self) -> None:
        response = self.client.get(f"/v1/index-funds/{self.fund_id}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["constituents"]), 2)
        self.assertEqual(body["profile"]["comparison_group"], "SQUAD")
        self.assertEqual(body["profile"]["radar_axes"][0]["label"], "Shooting")
        self.assertEqual(body["profile"]["radar_axes"][0]["score"], 80)
        self.assertEqual(body["cash_per_unit"], "2.5")
        (change,) = body["basket_changes"]
        self.assertEqual(change["kind"], "DELISTING")
        self.assertEqual(change["removed"][0]["player_name"], "Departed Player")

    def test_unknown_fund_is_404(self) -> None:
        response = self.client.get(f"/v1/index-funds/{uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "index_fund_not_found")
