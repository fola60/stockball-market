from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.ingestion.social.ports import SocialRepository
from app.jobs.models import (
    AggregateSocialSignalsJobPayload,
    IngestSocialFeedsJobPayload,
    ProcessSocialDocumentsJobPayload,
    WorkerJob,
)

from .service import (
    JobQueue,
    ScheduleClaimStore,
    ScheduleControlStore,
    ScheduledRunRepository,
)

SOCIAL_INGESTION_SCHEDULE_NAME = "social-feed-ingestion"


@dataclass(frozen=True)
class DueSocialSubscriptionDispatcher:
    """Discovers due subscriptions while preserving one small job per source."""

    repository: SocialRepository
    queue: JobQueue
    claim_store: ScheduleClaimStore
    control_store: ScheduleControlStore | None = None
    run_repository: ScheduledRunRepository | None = None
    batch_size: int = 100

    def dispatch_due(self, as_of: datetime) -> tuple[str, ...]:
        if self.control_store is not None and not self.control_store.is_enabled(
            SOCIAL_INGESTION_SCHEDULE_NAME, True
        ):
            return ()
        scheduled: list[str] = []
        window = as_of.replace(second=0, microsecond=0).isoformat()
        due = self.repository.list_due_subscriptions(as_of, limit=1)
        has_in_flight_run = (
            self.run_repository is not None
            and self.run_repository.has_in_flight(SOCIAL_INGESTION_SCHEDULE_NAME)
        )
        if (
            due
            and not has_in_flight_run
            and self.claim_store.claim(SOCIAL_INGESTION_SCHEDULE_NAME, window)
        ):
            job = WorkerJob.ingest_social_feeds(
                IngestSocialFeedsJobPayload(provider="ALL", limit=self.batch_size)
            )
            if self.run_repository is not None:
                run_id = uuid4()
                created = self.run_repository.create_run(
                    run_id,
                    SOCIAL_INGESTION_SCHEDULE_NAME,
                    window,
                    job.job_type,
                    job.payload,
                    False,
                )
                if created:
                    job = job.with_operation_run_id(run_id)
                else:
                    job = None
            if job is not None:
                try:
                    self.queue.enqueue(job)
                except Exception as error:
                    if self.run_repository is not None and job.operation_run_id is not None:
                        self.run_repository.mark_enqueue_failed(
                            job.operation_run_id,
                            f"failed to enqueue scheduled job: {error}",
                        )
                    raise
                scheduled.append(SOCIAL_INGESTION_SCHEDULE_NAME)
        processing_name = "social-document-processing"
        if self.claim_store.claim(processing_name, window):
            self.queue.enqueue(
                WorkerJob.process_social_documents(ProcessSocialDocumentsJobPayload())
            )
            scheduled.append(processing_name)
        if as_of.minute % 15 == 0:
            aggregation_name = "social-signal-aggregation"
            if self.claim_store.claim(aggregation_name, window):
                self.queue.enqueue(
                    WorkerJob.aggregate_social_signals(AggregateSocialSignalsJobPayload())
                )
                scheduled.append(aggregation_name)
        return tuple(scheduled)
