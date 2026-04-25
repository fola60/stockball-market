from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import sleep
from typing import Callable

from app.scheduler.service import SchedulerService


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SchedulerProcess:
    scheduler: SchedulerService
    clock: Callable[[], datetime] = _utc_now
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    def run_once(self) -> int:
        decisions = self.scheduler.schedule_due_jobs(self.clock())
        if decisions:
            self.logger.info("scheduled %s recurring jobs", len(decisions))
        return len(decisions)

    def run_forever(self, poll_seconds: int) -> None:
        while True:
            self.run_once()
            sleep(poll_seconds)
