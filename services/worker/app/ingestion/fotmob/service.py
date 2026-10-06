from __future__ import annotations

import logging
from datetime import UTC, datetime

from .client import FotMobClient
from .parsing import parse_ratings
from .repository import FotMobRepository

logger = logging.getLogger(__name__)


class FotMobIngestionService:
    def __init__(self, client: FotMobClient, repository: FotMobRepository):
        self.client = client
        self.repository = repository

    def ingest(
        self,
        *,
        league: int = 47,
        season: int,
        backfill: bool = False,
        refresh: bool = False,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(UTC)
        try:
            url, body, fixtures = self.client.fixtures(league, season)
            self.repository.save_document(url, body, "text/html")
            self.repository.discover(fixtures, league, season)
            due = self.repository.due(
                league, season, backfill=backfill, refresh=refresh, limit=limit, now=now
            )
            processed = failed = linked = observations = 0
            for fixture in due:
                match_id = str(fixture["id"])
                try:
                    url, body, data = self.client.match(match_id, refresh=refresh or not backfill)
                    self.repository.save_document(url, body, "application/json")
                    ratings = parse_ratings(data, fixture, league)
                    linked += self.repository.save_ratings(fixture, ratings, url)
                    processed += 1
                    observations += len(ratings)
                    logger.info(
                        "FotMob season=%s match=%s ratings=%s (%s/%s)",
                        season,
                        match_id,
                        len(ratings),
                        processed,
                        len(due),
                    )
                except Exception as error:
                    self.repository.record_error(match_id, str(error))
                    logger.warning("FotMob match %s remains pending: %s", match_id, error)
                    failed += 1
            identity_matches = self.repository.reconcile_player_matches()
            fetched_profiles = 0
            for player_id in self.repository.missing_profile_ids():
                try:
                    profile_url, profile_body, profile = self.client.player_profile(player_id)
                    self.repository.save_document(profile_url, profile_body, "text/html")
                    self.repository.record_profile(player_id, profile_url, profile)
                    fetched_profiles += 1
                except Exception as error:
                    logger.warning("FotMob player profile %s unavailable: %s", player_id, error)
            if fetched_profiles:
                identity_matches = self.repository.reconcile_player_matches()
            return {
                "season": season,
                "processed_matches": processed,
                "failed_matches": failed,
                "upserted_observations": observations,
                "matched_players": linked,
                "identity_matches": identity_matches,
                "fetched_profiles": fetched_profiles,
                **self.repository.coverage(league, season),
            }
        finally:
            self.client.close()
