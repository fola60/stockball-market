from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor, execute_values

from app.database import connection as pooled_connection

from .dataset import MatchHistory, load_match_history
from .ridge import RidgeModel
from .training import HorizonResult

SIGNAL_MATCH_RATING = "MATCH_RATING"


@dataclass(frozen=True)
class StoredModel:
    id: UUID
    trained_at: datetime
    # Only horizons that beat the baseline when the model was trained.
    models: Mapping[int, RidgeModel]
    evaluation: Mapping[str, Any]


@dataclass(frozen=True)
class PlayerForecast:
    player_id: str
    provider_player_id: str
    horizon_matches: int
    baseline: float
    predicted: float
    history_nineties: float
    contributions: Mapping[str, float]


class ForecastRepository(Protocol):
    def load_history(self) -> MatchHistory: ...

    def active_model(self) -> StoredModel | None: ...

    def save_model(
        self,
        results: Mapping[int, HorizonResult],
        *,
        promote: bool,
        reason: str,
        trained_at: datetime,
        trained_through: datetime | None,
    ) -> UUID: ...

    def save_forecasts(
        self, model_id: UUID, as_of: datetime, forecasts: Sequence[PlayerForecast]
    ) -> int: ...


class PostgresForecastRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def load_history(self) -> MatchHistory:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                return load_match_history(cursor)

    def active_model(self) -> StoredModel | None:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, trained_at, parameters, evaluation
                    FROM forecast_models
                    WHERE signal = %s AND status = 'ACTIVE'
                    """,
                    (SIGNAL_MATCH_RATING,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        evaluation = _object(row["evaluation"])
        return StoredModel(
            id=UUID(str(row["id"])),
            trained_at=row["trained_at"],
            models={
                int(horizon): RidgeModel.from_json(payload)
                for horizon, payload in _object(row["parameters"]).get("horizons", {}).items()
                if _object(evaluation.get(horizon)).get("usable")
            },
            evaluation=evaluation,
        )

    def save_model(
        self,
        results: Mapping[int, HorizonResult],
        *,
        promote: bool,
        reason: str,
        trained_at: datetime,
        trained_through: datetime | None,
    ) -> UUID:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                if promote:
                    cursor.execute(
                        """
                        UPDATE forecast_models
                        SET status = 'RETIRED', retired_at = %s
                        WHERE signal = %s AND status = 'ACTIVE'
                        """,
                        (trained_at, SIGNAL_MATCH_RATING),
                    )
                cursor.execute(
                    """
                    INSERT INTO forecast_models (
                        signal, status, decision_reason, trained_at, trained_through,
                        training_rows, parameters, evaluation
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        SIGNAL_MATCH_RATING,
                        "ACTIVE" if promote else "REJECTED",
                        reason,
                        trained_at,
                        trained_through,
                        max((result.training_rows for result in results.values()), default=0),
                        Json(
                            {
                                "horizons": {
                                    str(horizon): result.model.to_json()
                                    for horizon, result in results.items()
                                }
                            }
                        ),
                        Json(
                            {
                                str(horizon): result.evaluation()
                                for horizon, result in results.items()
                            }
                        ),
                    ),
                )
                return UUID(str(cursor.fetchone()[0]))

    def save_forecasts(
        self, model_id: UUID, as_of: datetime, forecasts: Sequence[PlayerForecast]
    ) -> int:
        """One forecast per player, horizon and day; a later run the same day replaces it."""
        if not forecasts:
            return 0
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                execute_values(
                    cursor,
                    """
                    INSERT INTO player_forecasts (
                        model_id, signal, player_id, provider_player_id, horizon_matches,
                        forecast_date, as_of, baseline, predicted, expected_change,
                        history_nineties, contributions
                    )
                    VALUES %s
                    ON CONFLICT (signal, player_id, horizon_matches, forecast_date) DO UPDATE
                    SET model_id = EXCLUDED.model_id,
                        provider_player_id = EXCLUDED.provider_player_id,
                        as_of = EXCLUDED.as_of,
                        baseline = EXCLUDED.baseline,
                        predicted = EXCLUDED.predicted,
                        expected_change = EXCLUDED.expected_change,
                        history_nineties = EXCLUDED.history_nineties,
                        contributions = EXCLUDED.contributions,
                        created_at = now()
                    """,
                    [
                        (
                            str(model_id),
                            SIGNAL_MATCH_RATING,
                            item.player_id,
                            item.provider_player_id,
                            item.horizon_matches,
                            as_of.date(),
                            as_of,
                            item.baseline,
                            item.predicted,
                            item.predicted - item.baseline,
                            item.history_nineties,
                            Json(dict(item.contributions)),
                        )
                        for item in forecasts
                    ],
                )
        return len(forecasts)


def _object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, Mapping) else {}
