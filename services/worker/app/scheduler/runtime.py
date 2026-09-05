from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import sleep
from typing import Callable, Protocol

from app.scheduler.service import SchedulerService


class SchedulerStatusReporter(Protocol):
    def record_scheduler_heartbeat(
        self, checked_at: datetime, scheduled_names: tuple[str, ...]
    ) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SchedulerProcess:
    scheduler: SchedulerService
    clock: Callable[[], datetime] = _utc_now
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))
    status_reporter: SchedulerStatusReporter | None = None

    def run_once(self) -> int:
        checked_at = self.clock()
        decisions = self.scheduler.schedule_due_jobs(checked_at)
        if self.status_reporter is not None:
            self.status_reporter.record_scheduler_heartbeat(
                checked_at, tuple(decision.schedule_name for decision in decisions)
            )
        if decisions:
            self.logger.info("scheduled %s recurring jobs", len(decisions))
        return len(decisions)

    def run_forever(self, poll_seconds: int) -> None:
        while True:
            self.run_once()
            sleep(poll_seconds)
