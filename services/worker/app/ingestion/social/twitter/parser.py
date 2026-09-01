from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Mapping

from bs4 import BeautifulSoup, Tag

from .models import TwitterPost, TwitterRateLimit, TwitterSearchPage

_STATUS_LINK_RE = re.compile(r"/([^/]+)/status/(\d+)")
_ENGAGEMENT_RE = re.compile(
    r"(\d[\d,]*)\s+repl(?:y|ies),\s+"
    r"(\d[\d,]*)\s+reposts?,\s+"
    r"(\d[\d,]*)\s+likes?,\s+"
    r"(\d[\d,]*)\s+bookmarks?,\s+"
    r"(\d[\d,]*)\s+views?"
)


def parse_search_page_html(
    html: str,
    *,
    since_id: str | None = None,
) -> TwitterSearchPage:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[TwitterPost] = []

    for article in soup.find_all("article", attrs={"data-testid": "tweet"}):
        post = _parse_article(article)
        if post is None:
            continue
        if since_id is not None and post.post_id <= since_id:
            continue
        posts.append(post)

    posts.sort(key=lambda p: p.post_id, reverse=True)
    newest_id = posts[0].post_id if posts else None

    return TwitterSearchPage(
        posts=tuple(posts),
        newest_id=newest_id,
        next_token=None,
        rate_limit=TwitterRateLimit(),
    )


def _parse_article(article: Tag) -> TwitterPost | None:
    post_id = _extract_post_id(article)
    if post_id is None:
        return None

    author = _extract_author(article)
    if author is None:
        return None

    text = _extract_text(article)
    if text is None:
        return None

    created_at = _extract_timestamp(article)

    return TwitterPost(
        post_id=post_id,
        author_id=author,
        text=text,
        created_at=created_at,
        lang=None,
        conversation_id=None,
        referenced_post_ids=(),
        edit_history_post_ids=(),
    )


def _extract_post_id(article: Tag) -> str | None:
    for link in article.find_all("a", href=True):
        match = _STATUS_LINK_RE.search(link["href"])
        if match is not None:
            return match.group(2)
    return None


def _extract_author(article: Tag) -> str | None:
    avatar = article.find("div", attrs={"data-testid": re.compile(r"^UserAvatar-Container-")})
    if avatar is not None:
        test_id = avatar.get("data-testid", "")
        match = re.match(r"UserAvatar-Container-(.+)", test_id)
        if match is not None:
            return match.group(1)

    user_name_div = article.find("div", attrs={"data-testid": "User-Name"})
    if user_name_div is not None:
        for link in user_name_div.find_all("a", href=True):
            match = _STATUS_LINK_RE.match(link["href"])
            if match is not None:
                return match.group(1)
            if link["href"].startswith("https://x.com/"):
                handle = link["href"].rstrip("/").rsplit("/", 1)[-1]
                if handle and handle not in {"home", "explore", "notifications", "search"}:
                    return handle

    return None


def _extract_text(article: Tag) -> str | None:
    text_div = article.find("div", attrs={"data-testid": "tweetText"})
    if text_div is None:
        return None
    parts: list[str] = []
    for child in text_div.descendants:
        if isinstance(child, str):
            stripped = child.strip()
            if stripped:
                parts.append(stripped)
    return " ".join(parts) if parts else None


def _extract_timestamp(article: Tag) -> datetime:
    time_el = article.find("time", attrs={"datetime": True})
    if time_el is None:
        return datetime.now(UTC)
    raw = time_el["datetime"]
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(str(value).replace(",", ""))
    except ValueError:
        return None
