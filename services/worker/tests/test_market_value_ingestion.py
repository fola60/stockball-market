from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from app.ingestion.market_values import (
    MarketValueImportService,
    MarketValueMatchStatus,
    MarketValueRow,
    TransfermarktCsvMarketValueReader,
)
from app.ingestion.market_values.matching import PlayerCandidate, match_market_value_row
from app.ingestion.market_values.models import MarketValueImportResult, MarketValueImportRow


class FakeMarketValueRepository:
    def __init__(
        self,
        candidates: list[PlayerCandidate],
        provider_refs: dict[str, UUID] | None = None,
    ) -> None:
        self.candidates = candidates
        self.provider_refs = provider_refs or {}
        self.saved_rows: list[MarketValueImportRow] = []

    def list_player_candidates(self) -> list[PlayerCandidate]:
        return self.candidates

    def list_provider_refs(self, source: str) -> dict[str, UUID]:
        return self.provider_refs

    def save_import(
        self,
        source: str,
        players_csv_path: str | None,
        valuations_csv_path: str,
        rows: list[MarketValueImportRow],
    ) -> MarketValueImportResult:
        self.saved_rows = rows
        return MarketValueImportResult(
            batch_id=UUID("00000000-0000-0000-0000-000000000001"),
            imported_rows=len(rows),
            matched_rows=sum(1 for row in rows if row.match.status is MarketValueMatchStatus.MATCHED),
            ambiguous_rows=sum(
                1 for row in rows if row.match.status is MarketValueMatchStatus.AMBIGUOUS
            ),
            unmatched_rows=sum(
                1 for row in rows if row.match.status is MarketValueMatchStatus.UNMATCHED
            ),
            rejected_rows=sum(1 for row in rows if row.match.status is MarketValueMatchStatus.REJECTED),
        )


class MarketValueCsvReaderTests(unittest.TestCase):
    def test_reader_uses_latest_valuation_and_player_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players_csv = root / "players.csv"
            valuations_csv = root / "player_valuations.csv"
            players_csv.write_text(
                "\n".join(
                    [
                        "player_id,first_name,last_name,name,date_of_birth,country_of_citizenship,current_club_name,url",
                        "405973,Bukayo,Saka,Bukayo Saka,2001-09-05 00:00:00,England,Arsenal FC,https://example.test/saka",
                    ]
                ),
                encoding="utf-8",
            )
            valuations_csv.write_text(
                "\n".join(
                    [
                        "player_id,date,market_value_in_eur,current_club_name,current_club_id,player_club_domestic_competition_id",
                        "405973,2025-01-01,120000000,Arsenal FC,11,GB1",
                        "405973,2025-06-01,150000000,Arsenal FC,11,GB1",
                    ]
                ),
                encoding="utf-8",
            )

            rows = TransfermarktCsvMarketValueReader().read(
                valuations_csv_path=valuations_csv,
                players_csv_path=players_csv,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_player_id, "405973")
        self.assertEqual(rows[0].source_player_name, "Bukayo Saka")
        self.assertEqual(rows[0].source_club, "Arsenal FC")
        self.assertEqual(rows[0].source_date_of_birth, date(2001, 9, 5))
        self.assertEqual(rows[0].value, Decimal("150000000"))
        self.assertEqual(rows[0].observed_at, datetime(2025, 6, 1, tzinfo=UTC))


class MarketValueMatchingTests(unittest.TestCase):
    def test_matches_by_name_and_date_of_birth(self) -> None:
        player_id = uuid4()
        row = _market_value_row(
            name="Bukayo Saka",
            club="Arsenal FC",
            date_of_birth=date(2001, 9, 5),
        )
        candidate = _candidate(
            player_id=player_id,
            name="Bukayo Saka",
            club="Arsenal",
            date_of_birth=date(2001, 9, 5),
        )

        match = match_market_value_row(row, None, [candidate])

        self.assertEqual(match.status, MarketValueMatchStatus.MATCHED)
        self.assertEqual(match.player_id, player_id)
        self.assertEqual(match.reason, "name_and_date_of_birth")

    def test_name_only_match_is_ambiguous(self) -> None:
        player_id = uuid4()
        row = _market_value_row(name="Bukayo Saka", club=None, date_of_birth=None)
        candidate = _candidate(player_id=player_id, name="Bukayo Saka", club="Arsenal")

        match = match_market_value_row(row, None, [candidate])

        self.assertEqual(match.status, MarketValueMatchStatus.AMBIGUOUS)
        self.assertIsNone(match.player_id)


class MarketValueImportServiceTests(unittest.TestCase):
    def test_import_service_matches_rows_and_saves_summary(self) -> None:
        player_id = uuid4()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players_csv = root / "players.csv"
            valuations_csv = root / "player_valuations.csv"
            players_csv.write_text(
                "\n".join(
                    [
                        "player_id,first_name,last_name,name,date_of_birth,country_of_citizenship,current_club_name,url",
                        "405973,Bukayo,Saka,Bukayo Saka,2001-09-05 00:00:00,England,Arsenal FC,https://example.test/saka",
                    ]
                ),
                encoding="utf-8",
            )
            valuations_csv.write_text(
                "\n".join(
                    [
                        "player_id,date,market_value_in_eur,current_club_name,current_club_id,player_club_domestic_competition_id",
                        "405973,2025-06-01,150000000,Arsenal FC,11,GB1",
                    ]
                ),
                encoding="utf-8",
            )
            repository = FakeMarketValueRepository(
                candidates=[
                    _candidate(
                        player_id=player_id,
                        name="Bukayo Saka",
                        club="Arsenal",
                        date_of_birth=date(2001, 9, 5),
                    )
                ]
            )
            service = MarketValueImportService(repository=repository)

            result = service.import_transfermarkt_csv(
                valuations_csv_path=valuations_csv,
                players_csv_path=players_csv,
            )

        self.assertEqual(result.imported_rows, 1)
        self.assertEqual(result.matched_rows, 1)
        self.assertEqual(repository.saved_rows[0].match.player_id, player_id)


def _market_value_row(
    name: str | None,
    club: str | None,
    date_of_birth: date | None,
) -> MarketValueRow:
    return MarketValueRow(
        source="transfermarkt_csv",
        source_player_id="405973",
        source_player_name=name,
        source_club=club,
        source_date_of_birth=date_of_birth,
        source_nationality="England",
        source_url="https://example.test/saka",
        value=Decimal("150000000"),
        currency="EUR",
        observed_at=datetime(2025, 6, 1, tzinfo=UTC),
        raw_payload={},
    )


def _candidate(
    player_id: UUID,
    name: str,
    club: str | None,
    date_of_birth: date | None = None,
) -> PlayerCandidate:
    return PlayerCandidate(
        player_id=player_id,
        display_name=name,
        club=club,
        date_of_birth=date_of_birth,
        nationality="England",
        metadata={},
    )


if __name__ == "__main__":
    unittest.main()
