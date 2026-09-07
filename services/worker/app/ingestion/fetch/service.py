from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator, Mapping
from urllib.parse import urljoin, urlparse

import httpx

from .models import FetchedContent, FetchRequest


class FetchError(Exception):
    """Base error for an external content fetch."""


class FetchPolicyError(FetchError):
    """The request violates the caller's approved URL policy."""


class FetchUnavailableError(FetchError):
    """The remote source could not be reached or returned a transient failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FetchResponseError(FetchError):
    """The source returned an unsuccessful or unsupported response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers: Mapping[str, str] = headers or {}


_BOT_DETECTION_MARKERS: tuple[str, ...] = (
    "checking if the site connection is secure",
    "verify you are human",
)

_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}

_HOST_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


class ContentFetchService:
    """Fetches bounded content from an explicitly allowlisted web source.

    Provider modules own authentication, parsing, persistence, and retry policy. This
    boundary only performs a safe GET and never follows a redirect without validating
    its destination against the original request's host policy.

    When ``browser_enabled`` is set and the allowlisted source answers a direct request
    with a bot-detection / access-denied response, the service transparently retries the
    fetch through a browser (mirroring the FBref client fallback). The browser
    path is optional so the service remains usable in environments without Chrome.
    """

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        user_agent: str = "StockballMarketFetcher/0.1",
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        browser_enabled: bool = False,
        use_undetected_chrome: bool = False,
        use_host_chrome: bool = True,
        host_chrome_binary_path: str | None = None,
        browser_idle_seconds: float = 2.0,
        browser_factory: Callable[..., object] | None = None,
        browser_user_data_dir: str | None = None,
        browser_profile_directory: str | None = None,
        browser_locale_code: str | None = None,
        bot_detection_markers: tuple[str, ...] = _BOT_DETECTION_MARKERS,
    ) -> None:
        self._transport = transport
        self._user_agent = user_agent
        self._client_factory = client_factory
        self._browser_enabled = browser_enabled
        self._use_undetected_chrome = use_undetected_chrome
        self._use_host_chrome = use_host_chrome
        self._host_chrome_binary_path = host_chrome_binary_path
        self._browser_idle_seconds = browser_idle_seconds
        self._browser_user_data_dir = browser_user_data_dir
        self._browser_profile_directory = self._validate_browser_profile(
            browser_profile_directory,
            browser_user_data_dir,
        )
        self._browser_locale_code = browser_locale_code
        self._bot_detection_markers = bot_detection_markers
        self._open_browser = browser_factory or self._default_open_browser

    def fetch(self, request: FetchRequest) -> FetchedContent:
        self._validate_request(request)
        if request.prefer_browser and self._browser_enabled:
            return self._fetch_with_browser(request, request.url, redirects=0)
        current_url = request.url
        redirects = 0
        headers = {"Accept": ", ".join(request.accepted_content_types), "User-Agent": self._user_agent}
        headers.update(request.headers)

        try:
            with self._client_factory(
                follow_redirects=False,
                timeout=request.timeout_seconds,
                transport=self._transport,
            ) as client:
                while True:
                    response = self._send(client, current_url, headers, request.max_bytes)
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        if redirects >= request.max_redirects:
                            raise FetchResponseError("fetch exceeded the redirect limit")
                        location = response.headers.get("location")
                        if not location:
                            raise FetchResponseError("redirect response omitted Location header")
                        current_url = urljoin(current_url, location)
                        self._validate_url(current_url, request.allowed_hosts)
                        redirects += 1
                        continue

                    try:
                        return self._to_content(request, current_url, response, redirects)
                    except (FetchResponseError, FetchUnavailableError):
                        if self._browser_enabled and self._is_access_denied(response):
                            return self._fetch_with_browser(request, current_url, redirects)
                        raise
        except httpx.TimeoutException as exc:
            raise FetchUnavailableError("fetch timed out") from exc
        except httpx.HTTPError as exc:
            raise FetchUnavailableError("fetch request failed") from exc

    @contextmanager
    def browser_session(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        max_page_bytes: int = 15_000_000,
    ) -> Iterator[object]:
        """Open an allowlisted interactive browser session for provider-owned discovery."""
        if not self._browser_enabled:
            raise FetchUnavailableError("interactive browser fetching is disabled")
        if not allowed_hosts:
            raise FetchPolicyError("browser sessions require at least one allowed host")
        if max_page_bytes <= 0:
            raise FetchPolicyError("browser session max_page_bytes must be positive")
        self._assert_user_data_dir_available()
        with ExitStack() as stack:
            try:
                browser = stack.enter_context(self._open_browser())
            except FetchError:
                raise
            except Exception as exc:
                raise FetchUnavailableError("interactive browser session failed") from exc
            yield _AllowlistedBrowserSession(
                browser,
                allowed_hosts,
                self._validate_url,
                max_page_bytes,
            )

    def _fetch_with_browser(
        self, request: FetchRequest, url: str, redirects: int
    ) -> FetchedContent:
        try:
            with self._open_browser() as browser:
                browser.open(url)
                if request.browser_wait_selector:
                    self._wait_for_selector(browser, request.browser_wait_selector)
                browser.sleep(self._browser_idle_seconds)
                body = browser.get_page_source()
        except FetchError:
            raise
        except Exception as exc:
            raise FetchUnavailableError(
                f"browser fallback failed for {url}"
            ) from exc

        if self._is_access_denied_text(body):
            raise FetchResponseError(
                "source blocked the browser fallback with bot detection, "
                f"url={url}"
            )

        content = body.encode("utf-8")
        if len(content) > request.max_bytes:
            raise FetchResponseError("browser response exceeds the configured size limit")

        return FetchedContent(
            requested_url=request.url,
            final_url=url,
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=content,
            content_type="text/html; charset=utf-8",
            redirect_count=redirects,
        )

    def _default_open_browser(self) -> object:
        if self._use_undetected_chrome:
            return self._open_undetected_browser()

        @contextmanager
        def _open() -> Iterator[object]:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            self._assert_user_data_dir_available()
            options = Options()
            options.page_load_strategy = "eager"
            if self._use_host_chrome:
                options.binary_location = (
                    self._host_chrome_binary_path or self._default_host_chrome_binary_path()
                )
            for argument in self._chrome_arguments():
                options.add_argument(argument)

            driver = webdriver.Chrome(options=options)
            try:
                yield _SeleniumBrowser(driver)
            finally:
                driver.quit()

        return _open()

    def _open_undetected_browser(self) -> object:
        @contextmanager
        def _open() -> Iterator[object]:
            from seleniumbase import SB

            self._assert_user_data_dir_available()
            browser_kwargs: dict[str, object] = {
                "uc": True,
                "headless": self._container_browser_is_headless(),
                "page_load_strategy": "eager",
            }
            if self._use_host_chrome:
                browser_kwargs["binary_location"] = (
                    self._host_chrome_binary_path or self._default_host_chrome_binary_path()
                )
            if self._browser_user_data_dir:
                browser_kwargs["user_data_dir"] = self._browser_user_data_dir
            if self._browser_profile_directory:
                browser_kwargs["chromium_arg"] = (
                    f"--profile-directory={self._browser_profile_directory}"
                )
            if self._browser_locale_code:
                browser_kwargs["locale_code"] = self._browser_locale_code

            with SB(**browser_kwargs) as browser:
                yield _SeleniumBaseBrowser(browser)

        return _open()

    def _chrome_arguments(self) -> tuple[str, ...]:
        arguments = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        # Containers cannot create Chrome's sandbox. Xvfb supplies a display for
        # headed browser sessions; one-off containers without it retain headless mode.
        if Path("/.dockerenv").exists():
            arguments.extend(
                (
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                )
            )
            if not os.environ.get("DISPLAY"):
                arguments.append("--headless=new")
        if self._browser_user_data_dir:
            arguments.append(f"--user-data-dir={self._browser_user_data_dir}")
        if self._browser_profile_directory:
            arguments.append(f"--profile-directory={self._browser_profile_directory}")
        return tuple(arguments)

    @staticmethod
    def _container_browser_is_headless() -> bool:
        return Path("/.dockerenv").exists() and not os.environ.get("DISPLAY")

    def _assert_user_data_dir_available(self) -> None:
        if not self._browser_user_data_dir:
            return
        lock_path = Path(self._browser_user_data_dir) / "SingletonLock"
        if os.path.lexists(lock_path):
            raise FetchUnavailableError(
                "Chrome user-data directory is already in use. Fully quit Chrome or "
                "configure a dedicated worker browser_user_data_dir."
            )

    @staticmethod
    def _validate_browser_profile(
        profile_directory: str | None,
        user_data_dir: str | None,
    ) -> str | None:
        if profile_directory is None:
            return None
        normalized = profile_directory.strip()
        if not normalized:
            raise ValueError("browser profile directory cannot be empty")
        if not user_data_dir:
            raise ValueError(
                "browser_profile_directory requires browser_user_data_dir"
            )
        if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("browser profile directory must be a Chrome profile name")
        return normalized

    @staticmethod
    def _default_host_chrome_binary_path() -> str:
        for candidate in _HOST_CHROME_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        raise FetchUnavailableError(
            "Host Chrome was requested for the browser fallback, but no Chrome "
            "binary was found. Pass host_chrome_binary_path explicitly."
        )

    @staticmethod
    def _wait_for_selector(browser: object, selector: str, timeout: float = 15.0) -> None:
        wait_method = getattr(browser, "wait_for_element_present", None)
        if wait_method is None:
            return
        try:
            wait_method(selector, timeout=timeout)
        except Exception:
            pass

    def _is_access_denied(self, response: httpx.Response) -> bool:
        if response.status_code in {401, 403}:
            return True
        return self._is_access_denied_text(response.text)

    def _is_access_denied_text(self, body: str) -> bool:
        lowered = body.lower()
        return any(marker in lowered for marker in self._bot_detection_markers)

    @staticmethod
    def _send(
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
        max_bytes: int,
    ) -> httpx.Response:
        request = client.build_request("GET", url, headers=headers)
        response = client.send(request, stream=True)
        try:
            declared_length = response.headers.get("content-length")
            if declared_length is not None and int(declared_length) > max_bytes:
                raise FetchResponseError("fetch response exceeds the configured size limit")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise FetchResponseError("fetch response exceeds the configured size limit")
            response._content = bytes(content)
            return response
        finally:
            response.close()

    @staticmethod
    def _to_content(
        request: FetchRequest,
        final_url: str,
        response: httpx.Response,
        redirects: int,
    ) -> FetchedContent:
        if response.status_code >= 500:
            raise FetchUnavailableError(
                f"source returned HTTP {response.status_code}", status_code=response.status_code
            )
        if not response.is_success:
            raise FetchResponseError(
                f"source returned HTTP {response.status_code}",
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        content_type = response.headers.get("content-type")
        media_type = None if content_type is None else content_type.split(";", 1)[0].strip().casefold()
        accepted = {value.casefold() for value in request.accepted_content_types}
        if media_type is not None and media_type not in accepted:
            raise FetchResponseError(
                f"unsupported response content type: {media_type}",
                status_code=response.status_code,
                headers=dict(response.headers),
            )
        return FetchedContent(
            requested_url=request.url,
            final_url=final_url,
            status_code=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            content_type=content_type,
            redirect_count=redirects,
        )

    @classmethod
    def _validate_request(cls, request: FetchRequest) -> None:
        if not request.allowed_hosts:
            raise FetchPolicyError("fetch requests require at least one allowed host")
        if request.timeout_seconds <= 0:
            raise FetchPolicyError("fetch timeout must be positive")
        if request.max_bytes <= 0:
            raise FetchPolicyError("fetch max_bytes must be positive")
        if request.max_redirects < 0:
            raise FetchPolicyError("fetch max_redirects cannot be negative")
        cls._validate_url(request.url, request.allowed_hosts)

    @staticmethod
    def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
        parsed = urlparse(url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            raise FetchPolicyError("fetch URLs must be absolute HTTP(S) URLs")
        if parsed.username or parsed.password:
            raise FetchPolicyError("fetch URLs must not contain credentials")
        normalized_hosts = {value.casefold().rstrip(".") for value in allowed_hosts}
        if host.casefold().rstrip(".") not in normalized_hosts:
            raise FetchPolicyError(f"fetch host is not approved: {host}")


class _SeleniumBrowser:
    """Small adapter that keeps Selenium details out of provider clients."""

    def __init__(self, driver: object) -> None:
        self._driver = driver

    def open(self, url: str) -> None:
        self._driver.get(url)

    def sleep(self, seconds: float) -> None:
        time.sleep(max(seconds, 0.0))

    def get_page_source(self) -> str:
        return str(self._driver.page_source)

    def get_current_url(self) -> str:
        return str(self._driver.current_url)

    def count_xpath(self, xpath: str) -> int:
        return len(self._visible_xpath_elements(xpath))

    def click_xpath(self, xpath: str, index: int = 0) -> None:
        from selenium.common.exceptions import ElementClickInterceptedException

        elements = self._visible_xpath_elements(xpath)
        if index < 0 or index >= len(elements):
            raise LookupError(f"browser XPath did not contain visible element {index}: {xpath}")
        element = elements[index]
        self._driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
            element,
        )
        try:
            element.click()
        except ElementClickInterceptedException:
            self._driver.execute_script("arguments[0].click();", element)

    def wait_for_xpath(self, xpath: str, timeout: float = 15.0) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(self._driver, timeout).until(
                expected_conditions.presence_of_element_located((By.XPATH, xpath))
            )
        except Exception as exc:
            raise TimeoutError(f"browser XPath did not appear: {xpath}") from exc

    def wait_for_url_change(self, previous_url: str, timeout: float = 15.0) -> None:
        from selenium.webdriver.support import expected_conditions
        from selenium.webdriver.support.ui import WebDriverWait

        try:
            WebDriverWait(self._driver, timeout).until(
                expected_conditions.url_changes(previous_url)
            )
        except Exception as exc:
            raise TimeoutError(f"browser URL did not change from {previous_url}") from exc

    def wait_for_element_present(self, selector: str, timeout: float = 15.0) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions
        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(self._driver, timeout).until(
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

    def _visible_xpath_elements(self, xpath: str) -> list[object]:
        from selenium.webdriver.common.by import By

        return [
            element
            for element in self._driver.find_elements(By.XPATH, xpath)
            if element.is_displayed()
        ]


class _SeleniumBaseBrowser:
    """Interactive adapter that keeps SeleniumBase UC navigation active."""

    def __init__(self, browser: object) -> None:
        self._browser = browser

    def open(self, url: str) -> None:
        self._browser.open(url)

    def sleep(self, seconds: float) -> None:
        self._browser.sleep(max(seconds, 0.0))

    def get_page_source(self) -> str:
        return str(self._browser.get_page_source())

    def get_current_url(self) -> str:
        return str(self._browser.get_current_url())

    def count_xpath(self, xpath: str) -> int:
        return int(self._browser.execute_script(self._visible_xpath_script(xpath, "count")))

    def click_xpath(self, xpath: str, index: int = 0) -> None:
        if index < 0:
            raise LookupError(f"browser XPath did not contain visible element {index}: {xpath}")
        target_xpath = self._browser.execute_script(
            self._visible_xpath_script(xpath, "path", index=index)
        )
        if not target_xpath:
            raise LookupError(f"browser XPath did not contain visible element {index}: {xpath}")
        try:
            self._browser.click(str(target_xpath))
        except Exception as exc:
            raise LookupError(
                f"browser XPath element {index} could not be clicked: {xpath}"
            ) from exc

    def wait_for_xpath(self, xpath: str, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.count_xpath(xpath):
                return
            self.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
        raise TimeoutError(f"browser XPath did not appear: {xpath}")

    def wait_for_url_change(self, previous_url: str, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_current_url() != previous_url:
                return
            self.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
        raise TimeoutError(f"browser URL did not change from {previous_url}")

    def wait_for_element_present(self, selector: str, timeout: float = 15.0) -> None:
        self._browser.wait_for_element_present(selector, timeout=timeout)

    @staticmethod
    def _visible_xpath_script(xpath: str, action: str, *, index: int = 0) -> str:
        action_script = "return visible.length;"
        if action == "path":
            action_script = f"""
                const target = visible[{index}];
                if (!target) return null;
                const segments = [];
                let current = target;
                while (current && current.nodeType === Node.ELEMENT_NODE) {{
                    let position = 1;
                    let sibling = current.previousElementSibling;
                    while (sibling) {{
                        if (sibling.tagName === current.tagName) position += 1;
                        sibling = sibling.previousElementSibling;
                    }}
                    segments.unshift(`${{current.tagName.toLowerCase()}}[${{position}}]`);
                    current = current.parentElement;
                }}
                return `/${{segments.join('/')}}`;
            """
        return f"""
            (() => {{
            const snapshot = document.evaluate(
                {json.dumps(xpath)},
                document,
                null,
                XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
                null
            );
            const visible = [];
            for (let i = 0; i < snapshot.snapshotLength; i += 1) {{
                const element = snapshot.snapshotItem(i);
                if (!(element instanceof Element)) continue;
                const style = window.getComputedStyle(element);
                const rendered = Boolean(
                    element.offsetWidth || element.offsetHeight || element.getClientRects().length
                );
                if (
                    rendered &&
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    style.opacity !== '0'
                ) {{
                    visible.push(element);
                }}
            }}
            {action_script}
            }})()
        """


class _AllowlistedBrowserSession:
    def __init__(
        self,
        browser: object,
        allowed_hosts: tuple[str, ...],
        validate_url: Callable[[str, tuple[str, ...]], None],
        max_page_bytes: int,
    ) -> None:
        self._browser = browser
        self._allowed_hosts = allowed_hosts
        self._validate_url = validate_url
        self._max_page_bytes = max_page_bytes

    def open(self, url: str) -> None:
        self._validate_url(url, self._allowed_hosts)
        self._browser.open(url)

    def sleep(self, seconds: float) -> None:
        self._browser.sleep(seconds)

    def get_page_source(self) -> str:
        page_source = str(self._browser.get_page_source())
        if len(page_source.encode("utf-8")) > self._max_page_bytes:
            raise FetchResponseError("browser page exceeds the configured size limit")
        return page_source

    def get_current_url(self) -> str:
        url = str(self._browser.get_current_url())
        self._validate_url(url, self._allowed_hosts)
        return url

    def count_xpath(self, xpath: str) -> int:
        return int(self._browser.count_xpath(xpath))

    def click_xpath(self, xpath: str, index: int = 0) -> None:
        self._browser.click_xpath(xpath, index=index)

    def wait_for_xpath(self, xpath: str, timeout: float = 15.0) -> None:
        self._browser.wait_for_xpath(xpath, timeout=timeout)

    def wait_for_url_change(self, previous_url: str, timeout: float = 15.0) -> None:
        self._browser.wait_for_url_change(previous_url, timeout=timeout)
        self.get_current_url()
