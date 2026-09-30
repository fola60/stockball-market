from __future__ import annotations

import unittest
from uuid import uuid4

from app.admin.service import AdminService, RedisJobPublisher


class FakeRepository:
    def __init__(self) -> None:
        self.created = []
        self.failed = []

    def create_run(self, run_id, operation_type, job_type, parameters):
        run = {"id": str(run_id), "operation_type": operation_type, "job_type": job_type,
               "status": "QUEUED", "parameters": dict(parameters)}
        self.created.append(run)
        return run

    def mark_enqueue_failed(self, run_id, message): self.failed.append((run_id, message))
    def list_runs(self, limit=100, **filters): return self.created[:limit]
    def get_run(self, run_id): return None
    def summary(self): return {}
    def list_bots(self): return []
    def list_profiles(self): return []
    def get_bot_details(self, bot_id): return None
    def list_trades(self, **kwargs):
        return {"items": [], "total": 0, "limit": kwargs["limit"], "offset": kwargs["offset"], "summary": {}}
    def get_trade_details(self, trade_id): return None


class FakePublisher:
    def __init__(self) -> None: self.messages = []
    def enqueue(self, message): self.messages.append(dict(message))


class AdminServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.publisher = FakePublisher()
        self.service = AdminService(self.repository, self.publisher)

    def test_enqueue_persists_run_and_correlates_worker_message(self) -> None:
        run = self.service.enqueue("INGEST_PLAYERS", {"season": 2026})
        message = self.publisher.messages[0]
        self.assertEqual(run["status"], "QUEUED")
        self.assertEqual(message["operation_run_id"], run["id"])
        self.assertEqual(message["payload"], {"league": 9, "season": 2026})

    def test_rejects_social_sentiment_and_unknown_commands(self) -> None:
        with self.assertRaises(ValueError):
            self.service.enqueue("INGEST_SOCIAL_SENTIMENT", {})

    def test_social_feed_ingestion_defaults_and_validates_scope(self) -> None:
        run = self.service.enqueue("INGEST_SOCIAL_FEEDS", {})

        self.assertEqual(run["parameters"], {"provider": "ALL", "limit": 100})
        self.assertEqual(self.publisher.messages[0]["job_type"], "INGEST_SOCIAL_FEEDS")

        with self.assertRaisesRegex(ValueError, "social provider"):
            self.service.enqueue("INGEST_SOCIAL_FEEDS", {"provider": "TWITTER"})
        with self.assertRaisesRegex(ValueError, "between 1 and 500"):
            self.service.enqueue("INGEST_SOCIAL_FEEDS", {"limit": 501})

    def test_requires_bootstrap_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "select all active bots"):
            self.service.enqueue("BOOTSTRAP_SYNTHETIC_PORTFOLIOS", {"dry_run": True})

    def test_spawn_count_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 500"):
            self.service.enqueue("SPAWN_SYNTHETIC_TRADERS", {"count": 501})

    def test_topups_default_and_validate_synthetic_trader_amount(self) -> None:
        run = self.service.enqueue("APPLY_TOPUPS", {})

        self.assertEqual(run["parameters"]["cadence"], "WEEKLY")
        self.assertEqual(run["parameters"]["synthetic_trader_amount"], "100000.0000")

        with self.assertRaisesRegex(ValueError, "greater than zero"):
            self.service.enqueue("APPLY_TOPUPS", {"synthetic_trader_amount": "0"})

    def test_force_tick_normalizes_selected_bot_ids(self) -> None:
        bot_ids = (uuid4(), uuid4())

        run = self.service.enqueue(
            "TICK_SYNTHETIC_TRADERS",
            {
                "force_timing": True,
                "bot_ids": [str(bot_id) for bot_id in bot_ids],
                "tick_count": 20,
            },
        )

        self.assertTrue(run["parameters"]["force_timing"])
        self.assertEqual(run["parameters"]["bot_ids"], [str(bot_id) for bot_id in bot_ids])
        self.assertEqual(run["parameters"]["tick_count"], 20)
        self.assertEqual(self.publisher.messages[0]["payload"], run["parameters"])

    def test_market_freeze_check_is_stamped_and_published(self) -> None:
        run = self.service.enqueue("CHECK_MARKET_FREEZES", {})

        self.assertIn("effective_at", run["parameters"])
        self.assertEqual(self.publisher.messages[0]["job_type"], "CHECK_MARKET_FREEZES")

    def test_force_tick_selection_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "no more than 500"):
            self.service.enqueue(
                "TICK_SYNTHETIC_TRADERS",
                {"force_timing": True, "bot_ids": [str(uuid4()) for _ in range(501)]},
            )

    def test_tick_count_is_bounded_and_requires_forced_timing(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.service.enqueue(
                "TICK_SYNTHETIC_TRADERS", {"force_timing": True, "tick_count": 101}
            )
        with self.assertRaisesRegex(ValueError, "require forced timing"):
            self.service.enqueue("TICK_SYNTHETIC_TRADERS", {"tick_count": 2})


class RedisJobPublisherTests(unittest.TestCase):
    def test_routes_trading_jobs_and_defaults_other_jobs_to_ingestion(self) -> None:
        class FakeRedis:
            def __init__(self):
                self.messages = []

            def rpush(self, queue_name, message):
                self.messages.append((queue_name, message))

        publisher = RedisJobPublisher.__new__(RedisJobPublisher)
        publisher._queue_name = "ingestion"
        publisher._job_queue_names = {
            "APPLY_TOPUPS": "trading",
            "SYNTHETIC_TRADER_TICK": "trading",
        }
        publisher._client = FakeRedis()

        publisher.enqueue({"job_type": "SYNTHETIC_TRADER_TICK", "payload": {}})
        publisher.enqueue({"job_type": "INGEST_SOCIAL_FEEDS", "payload": {}})

        self.assertEqual(
            [queue_name for queue_name, _ in publisher._client.messages],
            ["trading", "ingestion"],
        )


if __name__ == "__main__":
    unittest.main()
