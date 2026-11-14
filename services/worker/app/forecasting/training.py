"""Fit one model per horizon and judge it honestly against the rating the bots already use.

Evaluation is walk-forward: the newest season with enough matured rows is held out, the model
is fitted only on outcomes that were known before that season began, and its error there is
compared with predicting no change from the steadied season rating. The penalty is tuned
inside the training window, never on the holdout. The stored model is then refitted on
everything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Any, Mapping, Sequence

from .features import FEATURE_NAMES, HORIZONS, FeatureRow, Target
from .ridge import RidgeModel, RidgeProblem, prepare

ALPHAS: tuple[float, ...] = (3.0, 10.0, 30.0, 100.0, 300.0)
MIN_TRAINING_ROWS = 1000
MIN_HOLDOUT_ROWS = 300
# The newest share of the training window, used only to choose the penalty.
TUNING_SHARE = 0.25
# A retrained model may score this much worse than the active one before it is turned away:
# holdouts differ a little from run to run.
PROMOTION_TOLERANCE = 0.01

Sample = tuple[FeatureRow, Target]


@dataclass(frozen=True)
class HorizonResult:
    horizon: int
    model: RidgeModel
    training_rows: int
    holdout_season: int | None = None
    holdout_rows: int = 0
    baseline_rmse: float | None = None
    model_rmse: float | None = None
    # 1 - model MSE / baseline MSE on the holdout: above zero beats "no change".
    skill: float | None = None
    # Spearman correlation between predicted and realised change on the holdout.
    rank_correlation: float | None = None

    @property
    def usable(self) -> bool:
        return self.skill is not None and self.skill > 0

    def evaluation(self) -> dict[str, Any]:
        return {
            "training_rows": self.training_rows,
            "holdout_season": self.holdout_season,
            "holdout_rows": self.holdout_rows,
            "baseline_rmse": self.baseline_rmse,
            "model_rmse": self.model_rmse,
            "skill": self.skill,
            "rank_correlation": self.rank_correlation,
            "alpha": self.model.alpha,
            "usable": self.usable,
        }


def train(
    rows: Sequence[FeatureRow], feature_names: Sequence[str] = FEATURE_NAMES
) -> dict[int, HorizonResult]:
    """A result for every horizon with enough matured rows to fit."""
    results: dict[int, HorizonResult] = {}
    for horizon in HORIZONS:
        result = train_horizon(rows, horizon, feature_names)
        if result is not None:
            results[horizon] = result
    return results


def train_horizon(
    rows: Sequence[FeatureRow], horizon: int, feature_names: Sequence[str] = FEATURE_NAMES
) -> HorizonResult | None:
    samples: list[Sample] = sorted(
        ((row, row.targets[horizon]) for row in rows if horizon in row.targets),
        key=lambda sample: sample[0].as_of,
    )
    if len(samples) < MIN_TRAINING_ROWS:
        return None

    holdout_season = _holdout_season(samples)
    if holdout_season is None:
        alpha = _tune(samples, horizon, feature_names)
        return HorizonResult(
            horizon=horizon,
            model=_problem(samples, horizon, feature_names).solve(alpha),
            training_rows=len(samples),
        )

    holdout = [sample for sample in samples if sample[0].season >= holdout_season]
    holdout_start = holdout[0][0].as_of
    known = _known_before(samples, holdout_start)
    alpha = _tune(known, horizon, feature_names)
    evaluated = _problem(known, horizon, feature_names).solve(alpha)
    predictions = [evaluated.predict(row.features[horizon]) for row, _ in holdout]
    baseline_mse = _mse(holdout, [0.0] * len(holdout))
    model_mse = _mse(holdout, predictions)
    return HorizonResult(
        horizon=horizon,
        model=_problem(samples, horizon, feature_names).solve(alpha),
        training_rows=len(samples),
        holdout_season=holdout_season,
        holdout_rows=len(holdout),
        baseline_rmse=sqrt(baseline_mse),
        model_rmse=sqrt(model_mse),
        skill=1.0 - model_mse / baseline_mse if baseline_mse > 0 else None,
        rank_correlation=_spearman(predictions, [target.change for _, target in holdout]),
    )


def promotion_decision(
    candidate: Mapping[int, HorizonResult],
    active_evaluation: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    """Whether a freshly trained model should replace the active one, and why.

    It must beat the no-change baseline on at least one horizon, and must not score
    noticeably worse overall than the model it would replace.
    """
    usable = {horizon: result for horizon, result in candidate.items() if result.usable}
    if not usable:
        return False, "no horizon beat the season-rating baseline on the holdout"
    score = sum(result.skill or 0.0 for result in usable.values())
    if active_evaluation:
        active_score = sum(
            float(entry.get("skill") or 0.0)
            for entry in active_evaluation.values()
            if isinstance(entry, Mapping) and entry.get("usable")
        )
        if score < active_score - PROMOTION_TOLERANCE:
            return False, (
                f"holdout skill {score:.4f} is below the active model's {active_score:.4f}"
            )
    horizons = ", ".join(str(horizon) for horizon in sorted(usable))
    return True, f"beat the baseline at horizons {horizons} (total skill {score:.4f})"


def _holdout_season(samples: Sequence[Sample]) -> int | None:
    """The newest season that, with any after it, has enough rows to judge on, while leaving
    enough earlier outcomes to fit."""
    for season in sorted({row.season for row, _ in samples}, reverse=True):
        holdout = [sample for sample in samples if sample[0].season >= season]
        if len(holdout) < MIN_HOLDOUT_ROWS:
            continue
        if len(_known_before(samples, holdout[0][0].as_of)) >= MIN_TRAINING_ROWS:
            return season
        return None
    return None


def _known_before(samples: Sequence[Sample], moment: datetime) -> list[Sample]:
    return [sample for sample in samples if sample[1].matured_at < moment]


def _tune(samples: Sequence[Sample], horizon: int, feature_names: Sequence[str]) -> float:
    """The penalty that predicts the newest quarter of `samples` best from the rest."""
    cut = samples[int(len(samples) * (1.0 - TUNING_SHARE))][0].as_of
    fit = _known_before(samples, cut)
    check = [sample for sample in samples if sample[0].as_of >= cut]
    if len(fit) < MIN_TRAINING_ROWS // 2 or not check:
        return ALPHAS[len(ALPHAS) // 2]
    problem = _problem(fit, horizon, feature_names)
    errors = {}
    for alpha in ALPHAS:
        model = problem.solve(alpha)
        errors[alpha] = _mse(check, [model.predict(row.features[horizon]) for row, _ in check])
    return min(errors, key=lambda alpha: errors[alpha])


def _problem(
    samples: Sequence[Sample], horizon: int, feature_names: Sequence[str]
) -> RidgeProblem:
    return prepare(
        feature_names,
        [row.features[horizon] for row, _ in samples],
        [target.change for _, target in samples],
        [target.weight for _, target in samples],
    )


def _mse(samples: Sequence[Sample], predictions: Sequence[float]) -> float:
    weight = sum(target.weight for _, target in samples)
    return (
        sum(
            target.weight * (target.change - prediction) ** 2
            for (_, target), prediction in zip(samples, predictions, strict=True)
        )
        / weight
    )


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 3:
        return None
    ranked_left, ranked_right = _ranks(left), _ranks(right)
    mean_left = sum(ranked_left) / len(ranked_left)
    mean_right = sum(ranked_right) / len(ranked_right)
    covariance = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(ranked_left, ranked_right, strict=True)
    )
    spread = sqrt(
        sum((a - mean_left) ** 2 for a in ranked_left)
        * sum((b - mean_right) ** 2 for b in ranked_right)
    )
    return covariance / spread if spread > 0 else None


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, so ties do not invent an ordering."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for index in order[start : end + 1]:
            ranks[index] = (start + end) / 2.0
        start = end + 1
    return ranks
