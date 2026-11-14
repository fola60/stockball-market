"""A small weighted ridge regression with no dependencies beyond the standard library.

The worker image carries no numerical packages, and this problem is a few tens of thousands
of rows by a few dozen columns: plain normal equations solve it in seconds. A fitted model
is a list of coefficients, so it is stored as JSON and every forecast can be explained as a
sum of named contributions.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RidgeModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    alpha: float

    def contributions(self, features: Mapping[str, float | None]) -> dict[str, float]:
        """Each feature's share of the prediction. A missing value sits at the training mean
        and so contributes nothing."""
        return {
            name: coefficient * ((mean if (value := features.get(name)) is None else value) - mean)
            / scale
            for name, mean, scale, coefficient in zip(
                self.feature_names, self.means, self.scales, self.coefficients, strict=True
            )
        }

    def predict(self, features: Mapping[str, float | None]) -> float:
        return self.intercept + sum(self.contributions(features).values())

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "RIDGE",
            "feature_names": list(self.feature_names),
            "means": list(self.means),
            "scales": list(self.scales),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "alpha": self.alpha,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> RidgeModel:
        if payload.get("kind") != "RIDGE":
            raise ValueError(f"unsupported forecast model kind: {payload.get('kind')!r}")
        return cls(
            feature_names=tuple(str(name) for name in payload["feature_names"]),
            means=tuple(float(value) for value in payload["means"]),
            scales=tuple(float(value) for value in payload["scales"]),
            coefficients=tuple(float(value) for value in payload["coefficients"]),
            intercept=float(payload["intercept"]),
            alpha=float(payload["alpha"]),
        )


@dataclass(frozen=True)
class RidgeProblem:
    """The sufficient statistics of one dataset, so several penalties can be tried without
    passing over the rows again."""

    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    target_mean: float
    weight: float
    gram: tuple[tuple[float, ...], ...]
    moment: tuple[float, ...]

    def solve(self, alpha: float) -> RidgeModel:
        size = len(self.feature_names)
        # The penalty is per unit of weight, so it means the same on any amount of data.
        penalty = alpha * self.weight / max(size, 1)
        matrix = [list(row) for row in self.gram]
        for index in range(size):
            matrix[index][index] += penalty
        return RidgeModel(
            feature_names=self.feature_names,
            means=self.means,
            scales=self.scales,
            coefficients=tuple(_solve(matrix, list(self.moment))),
            intercept=self.target_mean,
            alpha=alpha,
        )


def prepare(
    feature_names: Sequence[str],
    rows: Sequence[Mapping[str, float | None]],
    targets: Sequence[float],
    weights: Sequence[float],
) -> RidgeProblem:
    if not rows or not len(rows) == len(targets) == len(weights):
        raise ValueError("ridge needs matching, non-empty rows, targets and weights")
    names = tuple(feature_names)
    size = len(names)
    total = sum(weights)
    if total <= 0:
        raise ValueError("ridge needs positive total weight")

    sums = [0.0] * size
    counts = [0.0] * size
    for row, weight in zip(rows, weights, strict=True):
        for index, name in enumerate(names):
            value = row.get(name)
            if value is not None:
                sums[index] += weight * value
                counts[index] += weight
    means = [sums[index] / counts[index] if counts[index] > 0 else 0.0 for index in range(size)]

    squares = [0.0] * size
    for row, weight in zip(rows, weights, strict=True):
        for index, name in enumerate(names):
            value = row.get(name)
            if value is not None:
                squares[index] += weight * (value - means[index]) ** 2
    # A constant column gets scale 1 and a zero coefficient.
    scales = [sqrt(squares[index] / total) or 1.0 for index in range(size)]
    target_mean = sum(w * t for w, t in zip(weights, targets, strict=True)) / total

    gram = [[0.0] * size for _ in range(size)]
    moment = [0.0] * size
    for row, target, weight in zip(rows, targets, weights, strict=True):
        vector = [
            0.0 if (value := row.get(name)) is None else (value - means[index]) / scales[index]
            for index, name in enumerate(names)
        ]
        centred = weight * (target - target_mean)
        for i, left in enumerate(vector):
            if left == 0.0:
                continue
            moment[i] += centred * left
            scaled = weight * left
            gram_row = gram[i]
            for j in range(i, size):
                gram_row[j] += scaled * vector[j]
    for i in range(size):
        for j in range(i):
            gram[i][j] = gram[j][i]
    return RidgeProblem(
        feature_names=names,
        means=tuple(means),
        scales=tuple(scales),
        target_mean=target_mean,
        weight=total,
        gram=tuple(tuple(row) for row in gram),
        moment=tuple(moment),
    )


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting. The ridge penalty keeps the system
    positive definite, so a zero pivot only appears with no penalty and no data."""
    size = len(vector)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-12:
            raise ValueError("ridge system is singular; use a positive penalty")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        vector[column], vector[pivot] = vector[pivot], vector[column]
        for row in range(column + 1, size):
            factor = matrix[row][column] / matrix[column][column]
            if factor == 0.0:
                continue
            for index in range(column, size):
                matrix[row][index] -= factor * matrix[column][index]
            vector[row] -= factor * vector[column]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        remainder = vector[row] - sum(
            matrix[row][index] * solution[index] for index in range(row + 1, size)
        )
        solution[row] = remainder / matrix[row][row]
    return solution
