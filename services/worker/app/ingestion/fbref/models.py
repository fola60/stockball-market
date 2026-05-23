from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


FBREF_PROVIDER = "FBREF"
DEFAULT_FBREF_BASE_URL = "https://fbref.com"
DEFAULT_FBREF_COMPETITION_ID = 9
DEFAULT_FBREF_COMPETITION = "Premier League"
DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS = 7.5
DEFAULT_FBREF_RATE_LIMIT_RETRY_SECONDS = 60.0
DEFAULT_FBREF_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_FBREF_USER_AGENT = (
    "StockballMarketWorker/0.1 "
    "(contact: engineering@stockball.local; provider=FBREF)"
)
DEFAULT_FBREF_STAT_TYPES: tuple[str, ...] = (
    "standard",
    "shooting",
    "passing",
    "defense",
    "keeper",
)


@dataclass(frozen=True)
class FbrefRawPage:
    provider: str
    source_url: str
    content_hash: str
    body: str
    status_code: int
    content_type: str | None
    fetched_at: datetime


class FbrefPageCache(Protocol):
    def get_latest_successful_page(self, source_url: str) -> FbrefRawPage | None: ...

    def save_page(self, page: FbrefRawPage) -> None: ...
