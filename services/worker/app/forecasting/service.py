from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from app.seasons import current_season

from .features import FeatureRow, build_rows
from .repository import ForecastRepository, PlayerForecast, StoredModel
from .training import promotion_decision, train

# The model is refitted once the active one is this old: about one round of matches.
RETRAIN_AFTER = timedelta(days=7)
# A forecast further than this from the season rating is a data problem, not a prediction.
MAX_EXPECTED_CHANGE = 1.0
# How many of a forecast's largest feature contributions are kept to explain it.
STORED_CONTRIBUTIONS = 6


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForecastService:
    repository: ForecastRepository
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    # Imports the season's latest match odds before a refresh. Odds only sharpen the team
    # strength features, so a failure here is logged and the refresh carries on.
    refresh_odds: Callable[[int], dict[str, Any]] | None = None

    def train(self, *, save: bool = True) -> dict[str, Any]:
        """Fit a model on all matured history and make it the active one if it earns it."""
        now = self.clock()
        history = self.repository.load_history()
        rows = build_rows(
            history.appearances,
            history.fixtures,
            birth_dates=history.birth_dates,
            market_values=history.market_values,
        )
        results = train(rows)
        active = self.repository.active_model()
        promote, reason = promotion_decision(results, active.evaluation if active else None)
        summary: dict[str, Any] = {
            "seasons": history.seasons,
            "appearances": len(history.appearances),
            "rows": len(rows),
            "promoted": promote and save,
            "decision": reason,
            "horizons": {
                str(horizon): result.evaluation() for horizon, result in results.items()
            },
        }
        if save and results:
            summary["model_id"] = str(
                self.repository.save_model(
                    results,
                    promote=promote,
                    reason=reason,
                    trained_at=now,
                    trained_through=max(
                        (item.kickoff_at for item in history.appearances), default=None
                    ),
                )
            )
        return summary

    def refresh(self, *, retrain: bool | None = None) -> dict[str, Any]:
        """Write today's forecasts from the active model, retraining first when it is due.

        `retrain` forces (True) or forbids (False) the retraining step; by default it runs
        when there is no active model or the active one is older than `RETRAIN_AFTER`.
        """
        now = self.clock()
        summary: dict[str, Any] = {}
        if self.refresh_odds is not None:
            try:
                summary["odds"] = self.refresh_odds(current_season(now))
            except Exception as error:  # noqa: BLE001
                logger.warning("match odds refresh failed: %s", error)
                summary["odds"] = {"status": "failed", "error": str(error)}
        active = self.repository.active_model()
        due = active is None or now - active.trained_at >= RETRAIN_AFTER
        if retrain or (retrain is None and due):
            summary["training"] = self.train()
            active = self.repository.active_model()
        if active is None or not active.models:
            return summary | {"status": "no_active_model", "forecasts": 0}

        history = self.repository.load_history()
        rows = build_rows(
            history.appearances,
            history.fixtures,
            birth_dates=history.birth_dates,
            market_values=history.market_values,
            live_as_of=now,
            live_season=current_season(now),
        )
        forecasts = [
            forecast
            for row in rows
            if row.player_id is not None
            for forecast in _forecasts(active, row)
        ]
        written = self.repository.save_forecasts(active.id, now, forecasts)
        return summary | {
            "status": "ok",
            "model_id": str(active.id),
            "horizons": sorted(active.models),
            "players": len({forecast.player_id for forecast in forecasts}),
            "forecasts": written,
        }


def _forecasts(model: StoredModel, row: FeatureRow) -> list[PlayerForecast]:
    forecasts = []
    for horizon, ridge in model.models.items():
        features = row.features[horizon]
        change = max(-MAX_EXPECTED_CHANGE, min(MAX_EXPECTED_CHANGE, ridge.predict(features)))
        contributions = sorted(
            ridge.contributions(features).items(), key=lambda item: abs(item[1]), reverse=True
        )
        forecasts.append(
            PlayerForecast(
                player_id=str(row.player_id),
                provider_player_id=row.provider_player_id,
                horizon_matches=horizon,
                baseline=row.baseline,
                predicted=row.baseline + change,
                history_nineties=row.history_nineties,
                contributions={
                    name: round(value, 5) for name, value in contributions[:STORED_CONTRIBUTIONS]
                },
            )
        )
    return forecasts
