from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class FetchRequest:
    """A bounded GET request for an explicitly approved external page."""

    url: str
    allowed_hosts: tuple[str, ...]
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 15.0
    max_bytes: int = 2_000_000
    max_redirects: int = 3
    accepted_content_types: tuple[str, ...] = (
        "text/html",
        "application/json",
        "application/xml",
        "text/xml",
        "text/plain",
    )
    browser_wait_selector: str | None = None
    prefer_browser: bool = False


@dataclass(frozen=True)
class FetchedContent:
    requested_url: str
    final_url: str
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    content_type: str | None
    redirect_count: int

    def text(self, encoding: str | None = None) -> str:
        return self.content.decode(encoding or _encoding_from_content_type(self.content_type), "replace")


def _encoding_from_content_type(content_type: str | None) -> str:
    if content_type:
        for parameter in content_type.split(";")[1:]:
            name, separator, value = parameter.strip().partition("=")
            if separator and name.casefold() == "charset":
                return value.strip('"')
    return "utf-8"
