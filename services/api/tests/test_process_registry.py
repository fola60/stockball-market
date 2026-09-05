from __future__ import annotations

import json
import unittest

from app.dev_operations.processes import RedisProcessRegistry


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
        definitions = __import__(
            "app.dev_operations.processes", fromlist=["configured_processes"]
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

    def test_set_enabled_persists_override(self) -> None:
        process = self.registry.set_enabled("bet365-odds", True)

        self.assertTrue(process["enabled"])
        self.assertEqual(
            self.redis.hashes["stockball:dev:schedule-overrides"]["bet365-odds"], "1"
        )


if __name__ == "__main__":
    unittest.main()
