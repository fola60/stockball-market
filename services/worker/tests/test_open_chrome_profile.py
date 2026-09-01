from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.open_chrome_profile import (
    discover_default_profile,
    load_profile_status,
    open_chrome_profile,
)


class ChromeProfileLauncherTests(unittest.TestCase):
    def test_reads_signed_in_profile_status_without_session_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            user_data_dir = Path(directory)
            (user_data_dir / "Default").mkdir()
            (user_data_dir / "Local State").write_text(
                json.dumps(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {
                                    "name": "Personal",
                                    "user_name": "person@example.test",
                                    "is_consented_primary_account": True,
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            status = load_profile_status(user_data_dir, "Default")

        self.assertTrue(status.signed_in)
        self.assertEqual(status.profile_name, "Personal")
        self.assertEqual(status.account_email, "person@example.test")

    def test_rejects_non_http_url_before_opening_chrome(self) -> None:
        with self.assertRaises(ValueError):
            open_chrome_profile(
                url="file:///private/data",
                profile_directory="Default",
                user_data_dir=Path("/tmp/chrome"),
                chrome_application="Google Chrome",
            )

    def test_discovers_last_used_signed_in_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            user_data_dir = Path(directory)
            (user_data_dir / "Default").mkdir()
            (user_data_dir / "Profile 1").mkdir()
            (user_data_dir / "Local State").write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 1",
                            "info_cache": {
                                "Default": {"is_consented_primary_account": True},
                                "Profile 1": {"is_consented_primary_account": True},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            profile = discover_default_profile(user_data_dir)

        self.assertEqual(profile, "Profile 1")

    @patch("scripts.open_chrome_profile.subprocess.run")
    def test_opens_a_new_chrome_instance_with_requested_profile(self, run: object) -> None:
        open_chrome_profile(
            url="https://x.com/home",
            profile_directory="Default",
            user_data_dir=Path("/tmp/stockball-chrome"),
            chrome_application="Google Chrome",
        )

        run.assert_called_once_with(
            [
                "open",
                "-n",
                "-a",
                "Google Chrome",
                "--args",
                "--user-data-dir=/tmp/stockball-chrome",
                "--profile-directory=Default",
                "https://x.com/home",
            ],
            check=True,
        )
