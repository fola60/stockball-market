"""Shared, order-independent percentile ranks. Equal evidence gets equal scores."""

from typing import Mapping, TypeVar

K = TypeVar("K")


def rank_percentiles(values: Mapping[K, float]) -> dict[K, float]:
    if len(values) < 2:
        return {key: 0.5 for key in values}
    ordered = sorted(values.values())
    first, last = {}, {}
    for index, value in enumerate(ordered):
        first.setdefault(value, index)
        last[value] = index
    return {
        key: (first[value] + last[value]) / (2 * (len(ordered) - 1))
        for key, value in values.items()
    }
