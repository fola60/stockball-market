from __future__ import annotations

import json
import unittest

from app.admin.processes import RedisProcessRegistry


class FakeRedis:
    def __init__(self) -> None:
        self.hashes = {}
        self.values = {}
        self.queues = {}

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def get(self, key):
        return self.values.get(key)

    def lrange(self, key, start, end):
        return list(self.queues.get(key, []))


class RedisProcessRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.registry = RedisProcessRegistry.__new__(RedisProcessRegistry)
        self.registry._client = self.redis
        self.registry._queue_name = "jobs"
        self.registry._executable_run_ids = None
        definitions = __import__(
            "app.admin.processes", fromlist=["configured_processes"]
        ).configured_processes()
        self.registry._definitions = {item.name: item for item in definitions}

    def test_snapshot_reports_scheduler_active_and_queued_work(self) -> None:
        self.redis.values["stockball:dev:scheduler-heartbeat"] = json.dumps(
            {"checked_at": "2026-09-04T20:00:00+00:00", "scheduled_names": []}
        )
        self.redis.values["stockball:dev:worker:active-job"] = json.dumps(
            {"job_type": "INGEST_PLAYER_STATS", "payload": {}, "attempt": 0}
        )
        self.redis.queues["jobs"] = [
            json.dumps(
                {
                    "job_type": "INGEST_BET365_ODDS",
                    "payload": {"mode": "LIVE"},
                    "attempt": 0,
                }
            )
        ]

        snapshot = self.registry.snapshot()

        self.assertTrue(snapshot["scheduler"]["online"])
        player_stats = next(
            item for item in snapshot["processes"] if item["name"] == "daily-player-stats"
        )
        live_odds = next(
            item for item in snapshot["processes"] if item["name"] == "bet365-live-odds"
        )
        self.assertTrue(player_stats["running"])
        self.assertEqual(live_odds["queued"], 1)

    def test_snapshot_combines_isolated_queues_and_active_workers(self) -> None:
        self.registry._queue_names = (
            "stockball:worker:trading",
            "stockball:worker:ingestion",
        )
        self.redis.values[
            "stockball:dev:worker:active-job:stockball:worker:ingestion"
        ] = json.dumps(
            {"job_type": "INGEST_SOCIAL_FEEDS", "payload": {}, "attempt": 0}
        )
        self.redis.queues["stockball:worker:trading"] = [
            json.dumps({"job_type": "SYNTHETIC_TRADER_TICK", "payload": {}})
        ]
        self.redis.queues["stockball:worker:ingestion"] = [
            json.dumps({"job_type": "INGEST_PLAYER_STATS", "payload": {}})
        ]

        snapshot = self.registry.snapshot()

        social = next(
            item
            for item in snapshot["processes"]
            if item["name"] == "social-feed-ingestion"
        )
        ticks = next(
            item
            for item in snapshot["processes"]
            if item["name"] == "synthetic-trader-ticks"
        )
        self.assertTrue(social["running"])
        self.assertEqual(ticks["queued"], 1)
        self.assertEqual(len(snapshot["queued_jobs"]), 2)
        self.assertEqual(len(snapshot["active_jobs"]), 1)

    def test_snapshot_excludes_non_executable_correlated_messages(self) -> None:
        self.registry._executable_run_ids = lambda run_ids: {"current-run"}
        self.redis.queues["jobs"] = [
            json.dumps(
                {
                    "job_type": "INGEST_BET365_ODDS",
                    "payload": {"mode": "PRE_MATCH"},
                    "operation_run_id": "superseded-run",
                }
            ),
            json.dumps(
                {
                    "job_type": "INGEST_BET365_ODDS",
                    "payload": {"mode": "PRE_MATCH"},
                    "operation_run_id": "current-run",
                }
            ),
        ]

        snapshot = self.registry.snapshot()

        pre_match = next(
            item for item in snapshot["processes"] if item["name"] == "bet365-odds"
        )
        self.assertEqual(pre_match["queued"], 1)
        self.assertEqual(len(snapshot["queued_jobs"]), 1)

    def test_set_enabled_persists_override(self) -> None:
        process = self.registry.set_enabled("bet365-odds", True)

        self.assertTrue(process["enabled"])
        self.assertEqual(
            self.redis.hashes["stockball:dev:schedule-overrides"]["bet365-odds"], "1"
        )

    def test_social_ingestion_is_a_controllable_recurring_process(self) -> None:
        social = next(
            item
            for item in self.registry.snapshot()["processes"]
            if item["name"] == "social-feed-ingestion"
        )

        self.assertTrue(social["enabled"])
        self.assertEqual(social["job_type"], "INGEST_SOCIAL_FEEDS")

        paused = self.registry.set_enabled("social-feed-ingestion", False)

        self.assertFalse(paused["enabled"])
        self.assertEqual(
            self.redis.hashes["stockball:dev:schedule-overrides"][
                "social-feed-ingestion"
            ],
            "0",
        )


if __name__ == "__main__":
    unittest.main()
