"""Commands that run the scheduler or a job worker, forever or for a single pass."""

from __future__ import annotations

from app.config import Settings
from app.entrypoints.factories import configure_logging
from app.entrypoints.processes import build_scheduler_process, build_worker_process


def _settings() -> Settings:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    return settings


def scheduler(args) -> int:
    settings = _settings()
    build_scheduler_process(settings).run_forever(settings.scheduler_poll_seconds)
    return 0


def schedule_once(args) -> int:
    build_scheduler_process(_settings()).run_once()
    return 0


def worker(args) -> int:
    settings = _settings()
    build_worker_process(settings).run_forever(settings.worker_block_seconds)
    return 0


def work_once(args) -> int:
    settings = _settings()
    build_worker_process(settings).run_once(settings.worker_block_seconds)
    return 0
