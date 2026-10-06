from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from app.ingestion.fotmob import FotMobIngestionService
from app.jobs.models import JobExecutionResult, JobType, WorkerJob
from app.seasons import resolve_season


@dataclass(frozen=True)
class FotMobRatingsJobHandler:
    service_factory: Callable[[], FotMobIngestionService]

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.INGEST_FOTMOB_RATINGS:
            raise ValueError(f"FotMob cannot process {job.job_type}")
        league = int(job.payload.get("league", 47))
        limit = int(job.payload.get("limit", 40))
        if league <= 0 or not 1 <= limit <= 500:
            raise ValueError("Invalid FotMob league or batch limit")
        result = self.service_factory().ingest(
            league=league,
            season=resolve_season(int(job.payload.get("season", 0))),
            limit=limit,
        )
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=datetime.now(UTC),
            successful_items=result["upserted_observations"],
            skipped_items=0,
            failed_items=result["failed_matches"],
            retryable_failures=result["failed_matches"],
            metrics=result,
        )
