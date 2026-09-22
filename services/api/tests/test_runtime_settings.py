from __future__ import annotations

import unittest

from app.dev_operations.runtime_settings import RuntimeSettingsRegistry


class FakeRepository:
    def __init__(self) -> None:
        self.values = {}
        self.changes = []

    def runtime_setting_values(self):
        return dict(self.values)

    def set_runtime_setting(self, key, value, *, actor, reason):
        self.values[key] = value
        self.changes.append(("set", key, value, actor, reason))

    def reset_runtime_setting(self, key, *, actor, reason):
        self.values.pop(key, None)
        self.changes.append(("reset", key, actor, reason))

    def list_admin_audit_events(self, limit=50):
        return []


class RuntimeSettingsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.registry = RuntimeSettingsRegistry(self.repository)

    def test_runtime_override_replaces_environment_default(self) -> None:
        result = self.registry.update(
            "player_stats_schedule_hour_utc", 8, actor="operator", reason="Move after feed close"
        )

        self.assertEqual(result["value"], 8)
        self.assertEqual(result["source"], "runtime")
        self.assertEqual(self.registry.values()["player_stats_schedule_hour_utc"], 8)

    def test_reset_returns_setting_to_environment_default(self) -> None:
        self.repository.values["player_stats_schedule_hour_utc"] = 8

        result = self.registry.update(
            "player_stats_schedule_hour_utc", None, actor="operator", reason="Restore default"
        )

        self.assertEqual(result["source"], "environment")

    def test_rejects_unknown_out_of_range_and_unreasoned_changes(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most 23"):
            self.registry.update("player_stats_schedule_hour_utc", 24, actor="operator", reason="Test")
        with self.assertRaisesRegex(ValueError, "unknown runtime setting"):
            self.registry.update("database_url", 1, actor="operator", reason="Test")
        with self.assertRaisesRegex(ValueError, "change reason"):
            self.registry.update("player_stats_schedule_hour_utc", 4, actor="operator", reason=" ")


if __name__ == "__main__":
    unittest.main()
