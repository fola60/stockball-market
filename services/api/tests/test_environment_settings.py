from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.admin.environment import EnvironmentFileService


class AuditRepository:
    def __init__(self) -> None:
        self.events = []

    def record_admin_audit_event(self, **event) -> None:
        self.events.append(event)


class EnvironmentFileServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.env_path = directory / ".env"
        self.example_path = directory / ".env.example"
        self.env_path.write_text("API_PORT=8000\nPOSTGRES_PASSWORD=secret\n")
        self.example_path.write_text(
            "API_PORT=8000\nPOSTGRES_PASSWORD=stockball\nSTOCKBALL_ADMIN_API_ENABLED=true\n"
        )
        self.audit = AuditRepository()
        self.service = EnvironmentFileService(
            self.env_path, self.example_path, self.audit
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_lists_all_variables_and_masks_sensitive_values(self) -> None:
        settings = {item["name"]: item for item in self.service.list()}

        self.assertEqual(settings["API_PORT"]["value"], "8000")
        self.assertIsNone(settings["POSTGRES_PASSWORD"]["value"])
        self.assertTrue(settings["POSTGRES_PASSWORD"]["has_value"])
        self.assertIn("STOCKBALL_ADMIN_API_ENABLED", settings)

    def test_updates_env_file_and_masks_sensitive_audit_values(self) -> None:
        self.service.update(
            "POSTGRES_PASSWORD",
            "new-secret",
            actor="operator",
            reason="Rotate local credential",
        )

        self.assertIn("POSTGRES_PASSWORD=new-secret", self.env_path.read_text())
        self.assertEqual(self.audit.events[0]["before_value"], "********")
        self.assertEqual(self.audit.events[0]["after_value"], "********")

    def test_validates_typed_values_and_unknown_names(self) -> None:
        with self.assertRaises(ValueError):
            self.service.update("API_PORT", "not-a-number", actor="operator", reason="Test")
        with self.assertRaises(ValueError):
            self.service.update("UNKNOWN", "value", actor="operator", reason="Test")


if __name__ == "__main__":
    unittest.main()
