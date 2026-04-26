from __future__ import annotations

from decimal import Decimal


def format_decimal(value: Decimal) -> str:
    return format(value, "f")
