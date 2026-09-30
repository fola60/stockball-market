from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.clients import (
    ApplyFreezeCommand,
    FreezeClient,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)

from .models import MATCH_DAY_REASON, MatchFreezeReconciliation, MatchFreezeWindow
from .repository import MatchFreezeRepository

logger = logging.getLogger(__name__)


@dataclass
class MatchFreezeService:
    """Keeps match-day freezes in line with the fixture list.

    Each run compares which players *should* be frozen (their club plays within the
    lineup-lock-to-settlement window) with the freezes that are open, then asks the trading
    engine to open the missing ones and release the finished ones. Running it repeatedly is
    safe: both engine commands are idempotent.
    """

    repository: MatchFreezeRepository
    engine: FreezeClient
    window: MatchFreezeWindow

    def reconcile(self, now: datetime) -> MatchFreezeReconciliation:
        fixtures = [
            fixture
            for fixture in self.repository.fixtures_near(now, self.window)
            if fixture.is_frozen_at(now, self.window)
        ]
        teams = sorted(
            {fixture.home_team_provider_id for fixture in fixtures}
            | {fixture.away_team_provider_id for fixture in fixtures}
        )
        instruments_by_team = self.repository.instruments_for_teams(teams)
        desired = {
            fixture.source_key: instruments_by_team.get(fixture.home_team_provider_id, set())
            | instruments_by_team.get(fixture.away_team_provider_id, set())
            for fixture in fixtures
        }
        open_freezes = self.repository.open_fixture_freezes()

        fixtures_frozen = instruments_frozen = fixtures_released = reactivated = 0
        failures: list[str] = []
        for source_key, instrument_ids in sorted(desired.items()):
            missing = instrument_ids - open_freezes.get(source_key, set())
            if not missing:
                continue
            try:
                result = self.engine.apply_freeze(
                    ApplyFreezeCommand(
                        reason=MATCH_DAY_REASON,
                        source_key=source_key,
                        instrument_ids=tuple(sorted(missing, key=str)),
                    )
                )
            except (TradingEngineClientError, TradingEngineUnavailableError) as error:
                failures.append(f"freeze {source_key}: {error}")
                continue
            fixtures_frozen += 1
            instruments_frozen += result.opened_count

        for source_key in sorted(open_freezes.keys() - desired.keys()):
            try:
                released = self.engine.release_freeze(source_key)
            except (TradingEngineClientError, TradingEngineUnavailableError) as error:
                failures.append(f"release {source_key}: {error}")
                continue
            fixtures_released += 1
            reactivated += len(released.reactivated_instrument_ids)

        if fixtures_frozen or fixtures_released:
            logger.info(
                "reconciled match-day freezes",
                extra={
                    "fixtures_frozen": fixtures_frozen,
                    "fixtures_released": fixtures_released,
                    "instruments_frozen": instruments_frozen,
                    "instruments_reactivated": reactivated,
                },
            )
        return MatchFreezeReconciliation(
            fixtures_frozen=fixtures_frozen,
            fixtures_released=fixtures_released,
            instruments_frozen=instruments_frozen,
            instruments_reactivated=reactivated,
            failures=tuple(failures),
        )
