from __future__ import annotations

import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from app.ingestion.fetch import (
    ContentFetchService,
    FetchPolicyError,
    FetchRequest,
    FetchResponseError,
    FetchUnavailableError,
)


@contextmanager
def _fake_browser(fake: object) -> object:
    yield fake


class FakeBrowser:
    def __init__(self, body: str) -> None:
        self._body = body
        self.opened: str | None = None
        self.slept = 0.0
        self.executed_scripts: list[str] = []

    def open(self, url: str) -> None:
        self.opened = url

    def sleep(self, seconds: float) -> None:
        self.slept = seconds

    def get_page_source(self) -> str:
        return self._body

    def get_current_url(self) -> str:
        if self.opened is None:
            raise RuntimeError("fake browser has not opened a URL")
        return self.opened

    def execute_script(self, script: str) -> int | bool:
        self.executed_scripts.append(script)
        if "data-stockball-click-target" in script:
            return True
        return 2

    def click(self, selector: str) -> None:
        self.executed_scripts.append(f"click:{selector}")


class ContentFetchServiceTests(unittest.TestCase):
    @patch("app.ingestion.fetch.service.Path.exists", return_value=True)
    def test_chrome_arguments_are_container_safe(self, _: object) -> None:
        arguments = ContentFetchService()._chrome_arguments()

        self.assertIn("--headless=new", arguments)
        self.assertIn("--no-sandbox", arguments)
        self.assertIn("--disable-dev-shm-usage", arguments)

    @patch("app.ingestion.fetch.service.Path.exists", return_value=False)
    def test_chrome_arguments_leave_local_browser_visible(self, _: object) -> None:
        arguments = ContentFetchService()._chrome_arguments()

        self.assertNotIn("--headless=new", arguments)
        self.assertNotIn("--no-sandbox", arguments)
        self.assertNotIn("--disable-dev-shm-usage", arguments)

    def test_fetches_allowlisted_content_as_typed_response(self) -> None:
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    content=b"<h1>Player update</h1>",
                )
            )
        )

        result = service.fetch(
            FetchRequest("https://publisher.test/story", allowed_hosts=("publisher.test",))
        )

        self.assertEqual(result.final_url, "https://publisher.test/story")
        self.assertEqual(result.text(), "<h1>Player update</h1>")

    def test_revalidates_redirect_destination(self) -> None:
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(302, headers={"location": "https://evil.test/"})
            )
        )

        with self.assertRaises(FetchPolicyError):
            service.fetch(FetchRequest("https://publisher.test/story", allowed_hosts=("publisher.test",)))

    def test_rejects_non_allowlisted_initial_url(self) -> None:
        with self.assertRaises(FetchPolicyError):
            ContentFetchService().fetch(
                FetchRequest("https://unapproved.test/story", allowed_hosts=("publisher.test",))
            )

    def test_rejects_oversized_declared_response(self) -> None:
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    headers={"content-type": "text/html", "content-length": "100"},
                    content=b"too large",
                )
            )
        )

        with self.assertRaises(FetchResponseError):
            service.fetch(
                FetchRequest(
                    "https://publisher.test/story",
                    allowed_hosts=("publisher.test",),
                    max_bytes=10,
                )
            )

    def test_follows_allowlisted_redirect(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/start":
                return httpx.Response(302, headers={"location": "/final"})
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"done")

        result = ContentFetchService(transport=httpx.MockTransport(handler)).fetch(
            FetchRequest("https://publisher.test/start", allowed_hosts=("publisher.test",))
        )

        self.assertEqual(result.final_url, "https://publisher.test/final")
        self.assertEqual(result.redirect_count, 1)

    def test_browser_fallback_returns_page_when_http_is_blocked(self) -> None:
        browser = FakeBrowser("<html><body>Real content</body></html>")
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403, content=b"Just a moment... verify you are human"
                )
            ),
            browser_enabled=True,
            browser_factory=lambda: _fake_browser(browser),
        )

        result = service.fetch(
            FetchRequest(
                "https://publisher.test/story",
                allowed_hosts=("publisher.test",),
                accepted_content_types=("text/html",),
            )
        )

        self.assertEqual(browser.opened, "https://publisher.test/story")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content_type, "text/html; charset=utf-8")
        self.assertEqual(result.text(), "<html><body>Real content</body></html>")

    def test_prefer_browser_skips_unusable_http_shell(self) -> None:
        browser = FakeBrowser("<article data-testid=\"tweet\">Rendered post</article>")
        requests = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal requests
            requests += 1
            return httpx.Response(200, content=b"<html>JavaScript required</html>")

        service = ContentFetchService(
            transport=httpx.MockTransport(handler),
            browser_enabled=True,
            browser_factory=lambda: _fake_browser(browser),
        )

        result = service.fetch(
            FetchRequest(
                "https://publisher.test/story",
                allowed_hosts=("publisher.test",),
                prefer_browser=True,
            )
        )

        self.assertEqual(requests, 0)
        self.assertEqual(browser.opened, "https://publisher.test/story")
        self.assertIn("Rendered post", result.text())

    def test_browser_fallback_disabled_raises_on_access_denied(self) -> None:
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403, content=b"Just a moment... verify you are human"
                )
            ),
            browser_enabled=False,
        )

        with self.assertRaises(FetchResponseError):
            service.fetch(
                FetchRequest("https://publisher.test/story", allowed_hosts=("publisher.test",))
            )

    def test_browser_fallback_still_denied_raises(self) -> None:
        browser = FakeBrowser("<html>verify you are human</html>")
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403, content=b"Just a moment... verify you are human"
                )
            ),
            browser_enabled=True,
            browser_factory=lambda: _fake_browser(browser),
        )

        with self.assertRaises(FetchResponseError):
            service.fetch(
                FetchRequest("https://publisher.test/story", allowed_hosts=("publisher.test",))
            )

    def test_browser_fallback_failure_raises_unavailable(self) -> None:
        def _broken() -> object:
            raise RuntimeError("no chrome")

        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, content=b"verify you are human")
            ),
            browser_enabled=True,
            browser_factory=_broken,
        )

        with self.assertRaises(FetchUnavailableError):
            service.fetch(
                FetchRequest("https://publisher.test/story", allowed_hosts=("publisher.test",))
            )

    def test_browser_fallback_respects_max_bytes(self) -> None:
        browser = FakeBrowser("x" * 50)
        service = ContentFetchService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, content=b"verify you are human")
            ),
            browser_enabled=True,
            browser_factory=lambda: _fake_browser(browser),
        )

        with self.assertRaises(FetchResponseError):
            service.fetch(
                FetchRequest(
                    "https://publisher.test/story",
                    allowed_hosts=("publisher.test",),
                    max_bytes=10,
                )
            )

    def test_interactive_browser_session_bounds_rendered_page(self) -> None:
        browser = FakeBrowser("rendered page")
        service = ContentFetchService(
            browser_enabled=True,
            browser_factory=lambda: _fake_browser(browser),
        )

        with service.browser_session(
            allowed_hosts=("publisher.test",),
            max_page_bytes=5,
        ) as session:
            session.open("https://publisher.test/story#/client-route")
            with self.assertRaises(FetchResponseError):
                session.get_page_source()

    def test_interactive_browser_session_rejects_off_host_result(self) -> None:
        browser = FakeBrowser("rendered page")
        service = ContentFetchService(
            browser_enabled=True,
            browser_factory=lambda: _fake_browser(browser),
        )

        with service.browser_session(allowed_hosts=("publisher.test",)) as session:
            session.open("https://publisher.test/story")
            browser.opened = "https://unapproved.test/result"
            with self.assertRaises(FetchPolicyError):
                session.get_current_url()

    def test_browser_profile_is_passed_to_chrome_with_user_data_directory(self) -> None:
        service = ContentFetchService(
            browser_enabled=True,
            browser_user_data_dir="/Users/test/Library/Application Support/Google/Chrome",
            browser_profile_directory="Profile 1",
            host_chrome_binary_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )

        self.assertEqual(
            service._chrome_arguments(),
            (
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--user-data-dir=/Users/test/Library/Application Support/Google/Chrome",
                "--profile-directory=Profile 1",
            ),
        )

    @patch("seleniumbase.SB")
    def test_undetected_browser_uses_seleniumbase_uc_mode(self, seleniumbase: object) -> None:
        browser = FakeBrowser("rendered page")
        seleniumbase.return_value = _fake_browser(browser)
        service = ContentFetchService(
            browser_enabled=True,
            use_undetected_chrome=True,
            host_chrome_binary_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )

        with service.browser_session(allowed_hosts=("publisher.test",)) as session:
            session.open("https://publisher.test/story")
            self.assertEqual(session.count_xpath("//span[normalize-space()='Football']"), 2)
            session.wait_for_xpath("//span[normalize-space()='Football']", timeout=0.1)
            session.click_xpath("//span[normalize-space()='Football']", index=1)

        seleniumbase.assert_called_once_with(
            uc=True,
            headless=False,
            page_load_strategy="eager",
            binary_location="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        self.assertEqual(browser.opened, "https://publisher.test/story")
        self.assertTrue(any("document.evaluate" in script for script in browser.executed_scripts))
        self.assertTrue(any("visible[1]" in script for script in browser.executed_scripts))

    def test_browser_profile_requires_user_data_directory(self) -> None:
        with self.assertRaises(ValueError):
            ContentFetchService(browser_profile_directory="Default")

    def test_locked_chrome_user_data_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            Path(directory, "SingletonLock").touch()
            service = ContentFetchService(browser_user_data_dir=directory)

            with self.assertRaises(FetchUnavailableError) as raised:
                service._assert_user_data_dir_available()

        self.assertIn("already in use", str(raised.exception))
