from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from threading import RLock
from typing import Any, Iterable, Mapping
from uuid import UUID

from app.clients.trading_engine import OrderSide

from .models import MarketTradeSample, PricePoint


@dataclass(frozen=True)
class _PriceEntry:
    id: UUID
    instrument_id: UUID
    point: PricePoint


@dataclass(frozen=True)
class _TradeEntry:
    id: UUID
    sample: MarketTradeSample


class RollingMarketHistoryCache:
    """Keeps a rolling market window and refreshes it with small overlapping deltas."""

    def __init__(self, *, cursor_overlap: timedelta = timedelta(minutes=5)) -> None:
        self._cursor_overlap = cursor_overlap
        self._prices: dict[UUID, dict[UUID, _PriceEntry]] = {}
        self._trades: dict[UUID, dict[UUID, _TradeEntry]] = {}
        self._prices_scanned_through: datetime | None = None
        self._trades_scanned_through: datetime | None = None
        self._lock = RLock()

    def next_price_since(self, window_start: datetime, through: datetime) -> datetime | None:
        with self._lock:
            if self._prices_scanned_through is None:
                return window_start
            if through < self._prices_scanned_through:
                self._prices.clear()
                self._prices_scanned_through = None
                return window_start
            if through == self._prices_scanned_through:
                return None
            return max(window_start, self._prices_scanned_through - self._cursor_overlap)

    def next_trade_since(self, window_start: datetime, through: datetime) -> datetime | None:
        with self._lock:
            if self._trades_scanned_through is None:
                return window_start
            if through < self._trades_scanned_through:
                self._trades.clear()
                self._trades_scanned_through = None
                return window_start
            if through == self._trades_scanned_through:
                return None
            return max(window_start, self._trades_scanned_through - self._cursor_overlap)

    def record_prices(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        window_start: datetime,
        scanned_through: datetime,
    ) -> None:
        with self._lock:
            for row in rows:
                entry = _PriceEntry(
                    id=UUID(str(row["id"])),
                    instrument_id=UUID(str(row["instrument_id"])),
                    point=PricePoint(
                        price=Decimal(str(row["new_price"])),
                        captured_at=row["captured_at"],
                    ),
                )
                self._prices.setdefault(entry.instrument_id, {})[entry.id] = entry
            self._prices_scanned_through = scanned_through
            self._evict_prices(window_start)

    def record_trades(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        window_start: datetime,
        scanned_through: datetime,
    ) -> None:
        with self._lock:
            for row in rows:
                entry = _TradeEntry(
                    id=UUID(str(row["id"])),
                    sample=MarketTradeSample(
                        instrument_id=UUID(str(row["instrument_id"])),
                        side=OrderSide(str(row["side"])),
                        quantity=Decimal(str(row["shares"])),
                        gross_amount=Decimal(str(row["gross_amount"])),
                        account_id=UUID(str(row["account_id"])),
                        executed_at=row["executed_at"],
                    ),
                )
                self._trades.setdefault(entry.sample.instrument_id, {})[entry.id] = entry
            self._trades_scanned_through = scanned_through
            self._evict_trades(window_start)

    def prices(
        self,
        instrument_ids: Iterable[UUID],
        *,
        window_start: datetime,
        through: datetime,
    ) -> dict[str, list[PricePoint]]:
        with self._lock:
            return {
                str(instrument_id): sorted(
                    (
                        entry.point
                        for entry in self._prices.get(instrument_id, {}).values()
                        if window_start <= entry.point.captured_at <= through
                    ),
                    key=lambda point: point.captured_at,
                )
                for instrument_id in instrument_ids
                if instrument_id in self._prices
            }

    def trades(
        self,
        instrument_ids: Iterable[UUID],
        *,
        window_start: datetime,
        through: datetime,
    ) -> dict[str, list[MarketTradeSample]]:
        with self._lock:
            return {
                str(instrument_id): sorted(
                    (
                        entry.sample
                        for entry in self._trades.get(instrument_id, {}).values()
                        if window_start <= entry.sample.executed_at <= through
                    ),
                    key=lambda sample: sample.executed_at,
                )
                for instrument_id in instrument_ids
                if instrument_id in self._trades
            }

    def _evict_prices(self, window_start: datetime) -> None:
        for instrument_id, entries in tuple(self._prices.items()):
            retained = {
                entry_id: entry
                for entry_id, entry in entries.items()
                if entry.point.captured_at >= window_start
            }
            if retained:
                self._prices[instrument_id] = retained
            else:
                del self._prices[instrument_id]

    def _evict_trades(self, window_start: datetime) -> None:
        for instrument_id, entries in tuple(self._trades.items()):
            retained = {
                entry_id: entry
                for entry_id, entry in entries.items()
                if entry.sample.executed_at >= window_start
            }
            if retained:
                self._trades[instrument_id] = retained
            else:
                del self._trades[instrument_id]
