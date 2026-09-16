from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Protocol

from .csv_importer import DEFAULT_CURRENCY, DEFAULT_SOURCE, TransfermarktCsvMarketValueReader
from .matching import PlayerCandidate, match_market_value_row, normalize_name
from .models import MarketValueImportResult, MarketValueImportRow, MarketValueRow


class MarketValueRepository(Protocol):
    def list_player_candidates(self) -> list[PlayerCandidate]: ...

    def list_provider_refs(self, source: str): ...

    def save_import(
        self,
        source: str,
        players_csv_path: str | None,
        valuations_csv_path: str,
        rows: list[MarketValueImportRow],
    ) -> MarketValueImportResult: ...


class MarketValueImportService:
    def __init__(
        self,
        repository: MarketValueRepository,
        reader: TransfermarktCsvMarketValueReader | None = None,
    ) -> None:
        self._repository = repository
        self._reader = reader or TransfermarktCsvMarketValueReader()

    def import_transfermarkt_csv(
        self,
        valuations_csv_path: Path,
        players_csv_path: Path | None = None,
        source: str = DEFAULT_SOURCE,
        currency: str = DEFAULT_CURRENCY,
    ) -> MarketValueImportResult:
        rows = self._reader.read(
            valuations_csv_path=valuations_csv_path,
            players_csv_path=players_csv_path,
            source=source,
            currency=currency,
        )
        candidates = self._repository.list_player_candidates()
        provider_refs = self._repository.list_provider_refs(source)
        source_name_counts = Counter(
            normalize_name(row.source_player_name)
            for row in rows
            if normalize_name(row.source_player_name)
        )
        import_rows = [
            self._match_row(row, candidates, provider_refs, source_name_counts)
            for row in rows
        ]
        return self._repository.save_import(
            source=source,
            players_csv_path=None if players_csv_path is None else str(players_csv_path),
            valuations_csv_path=str(valuations_csv_path),
            rows=import_rows,
        )

    def _match_row(
        self,
        row: MarketValueRow,
        candidates: list[PlayerCandidate],
        provider_refs,
        source_name_counts: Counter[str],
    ) -> MarketValueImportRow:
        existing_ref = provider_refs.get(row.source_player_id)
        return MarketValueImportRow(
            market_value=row,
            match=match_market_value_row(
                row,
                existing_ref,
                candidates,
                source_name_occurrences=source_name_counts.get(
                    normalize_name(row.source_player_name),
                    0,
                ),
            ),
        )
