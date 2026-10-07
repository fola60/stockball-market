from __future__ import annotations

import logging
from datetime import UTC, datetime

from .client import FotMobClient, FotMobImageMissing
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
            images = self._ingest_images(limit=20, now=now)
            return {
                "season": season,
                "processed_matches": processed,
                "failed_matches": failed,
                "upserted_observations": observations,
                "matched_players": linked,
                "identity_matches": identity_matches,
                "fetched_profiles": fetched_profiles,
                "images": images,
                **self.repository.coverage(league, season),
            }
        finally:
            self.client.close()

    def ingest_images(self, *, limit: int = 200, now: datetime | None = None) -> dict:
        try:
            return self._ingest_images(limit=limit, now=now or datetime.now(UTC))
        finally:
            self.client.close()

    def _ingest_images(self, *, limit: int, now: datetime) -> dict:
        fetched = missing = failed = 0
        for player_id in self.repository.due_images(limit=limit, now=now):
            try:
                image = self.client.player_image(player_id)
                self.repository.save_image(player_id, image)
                fetched += 1
            except FotMobImageMissing as error:
                self.repository.record_image_failure(player_id, missing=True, error=str(error))
                missing += 1
            except Exception as error:
                self.repository.record_image_failure(player_id, missing=False, error=str(error))
                logger.warning("FotMob player image %s unavailable: %s", player_id, error)
                failed += 1
        return {
            "fetched": fetched,
            "missing": missing,
            "failed": failed,
            **self.repository.image_coverage(),
        }
