from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.index_funds.models import (
    IndexConstituentRecord,
    IndexFundDetailRecord,
    IndexFundProfileRecord,
    IndexFundRecord,
)
from app.index_funds.repository import IndexFundsRepository
from app.instruments.models import PlayerStatsRecord, RadarAxisRecord, RadarMetricRecord
from app.instruments.repository import InstrumentsRepository

# Outfield axes, then the keeper's, then the ones every player has. Keeper-only axes beyond
# shot stopping would describe one or two players, so they stay on the players' own pages.
PROFILE_AXES = (
    "Attacking output",
    "Shooting",
    "Finishing",
    "Ball winning",
    "Shot stopping",
    "Discipline",
    "Availability",
)


class IndexFundNotFoundError(Exception):
    def __init__(self, instrument_id: UUID) -> None:
        self.instrument_id = instrument_id
        super().__init__(f"index fund {instrument_id} was not found")


class IndexFundsService:
    def __init__(
        self,
        repository: IndexFundsRepository,
        instruments_repository: InstrumentsRepository,
    ) -> None:
        self._repository = repository
        self._instruments = instruments_repository

    def list_index_funds(self) -> list[IndexFundRecord]:
        return self._repository.list_index_funds()

    def get_index_fund(self, instrument_id: UUID) -> IndexFundDetailRecord:
        fund = self._repository.get_index_fund(instrument_id)
        if fund is None:
            raise IndexFundNotFoundError(instrument_id)
        constituents = self._repository.list_constituents(instrument_id)
        stats = self._instruments.list_player_stats(
            [constituent.instrument_id for constituent in constituents]
        )
        return IndexFundDetailRecord(
            fund=fund,
            constituents=constituents,
            profile=squad_profile(constituents, stats),
        )


def squad_profile(
    constituents: list[IndexConstituentRecord],
    stats: dict[UUID, PlayerStatsRecord],
) -> IndexFundProfileRecord | None:
    """Each axis and metric as the average of its players' percentiles, weighted by each
    player's share of a unit's value, over the players the axis applies to."""
    weights = {
        constituent.instrument_id: Decimal(constituent.shares_per_unit)
        * Decimal(constituent.current_price)
        for constituent in constituents
        if constituent.instrument_id in stats
    }
    if not weights:
        return None

    axes: list[RadarAxisRecord] = []
    for label in PROFILE_AXES:
        players = [
            (weights[instrument_id], axis)
            for instrument_id, record in stats.items()
            if instrument_id in weights
            for axis in record.radar_axes
            if axis.label == label
        ]
        if not players:
            continue
        components: dict[str, list[tuple[Decimal, int]]] = {}
        for weight, axis in players:
            for component in axis.components:
                components.setdefault(component.label, []).append((weight, component.score))
        axes.append(
            RadarAxisRecord(
                label=label,
                score=_weighted([(weight, axis.score) for weight, axis in players]),
                value=_players(len(players)),
                components=[
                    RadarMetricRecord(
                        label=component,
                        score=_weighted(scores),
                        value=_players(len(scores)),
                    )
                    for component, scores in components.items()
                ],
            )
        )

    return IndexFundProfileRecord(
        comparison_group="SQUAD",
        comparison_size=len(weights),
        radar_axes=axes,
    )


def _weighted(scores: list[tuple[Decimal, int]]) -> int:
    total = sum((weight for weight, _ in scores), Decimal("0"))
    if total <= 0:
        return round(sum(score for _, score in scores) / len(scores))
    return round(sum(weight * score for weight, score in scores) / total)


def _players(count: int) -> str:
    return f"{count} player{'' if count == 1 else 's'}"
