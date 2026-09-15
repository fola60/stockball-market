from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterable
from urllib.parse import urljoin
from uuid import UUID

from bs4 import BeautifulSoup

from ...domain import PermanentProviderError, SocialDocument, SocialDocumentKind, SocialProvider

_SPACE = re.compile(r"\s+")


def parse_feed(
    content: bytes,
    *,
    source_id: UUID,
    feed_url: str,
    max_items: int = 100,
) -> tuple[SocialDocument, ...]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise PermanentProviderError("RSS/Atom feed contains malformed XML") from error
    local_name = _local(root.tag)
    if local_name == "feed":
        entries = [element for element in root if _local(element.tag) == "entry"]
        mapper = _atom_entry
    elif local_name in {"rss", "rdf"}:
        entries = [element for element in root.iter() if _local(element.tag) == "item"]
        mapper = _rss_item
    else:
        raise PermanentProviderError("document is not a supported RSS 2.0 or Atom feed")
    documents: list[SocialDocument] = []
    for entry in entries[: max(max_items, 0)]:
        document = mapper(entry, source_id, feed_url)
        if document is not None:
            documents.append(document)
    return tuple(documents)


def sanitize_html(value: str) -> str:
    soup = BeautifulSoup(unescape(value), "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    return _SPACE.sub(" ", soup.get_text(" ", strip=True)).strip()


def _rss_item(item: ET.Element, source_id: UUID, feed_url: str) -> SocialDocument | None:
    title = _child_text(item, "title")
    description = _child_text(item, "description") or _child_text(item, "encoded")
    text = sanitize_html(" ".join(value for value in (title, description) if value))
    link = _child_text(item, "link")
    canonical_url = urljoin(feed_url, link) if link else feed_url
    external_id = _child_text(item, "guid") or link or _fallback_id(canonical_url, text)
    published = _parse_datetime(
        _child_text(item, "pubDate") or _child_text(item, "date")
    )
    if published is None:
        return None
    author = _child_text(item, "author") or _child_text(item, "creator")
    language = _child_text(item, "language")
    return SocialDocument(
        provider=SocialProvider.RSS,
        external_id=external_id,
        source_id=source_id,
        document_kind=SocialDocumentKind.FEED_ENTRY,
        author_external_id=author,
        text=text,
        published_at=published,
        canonical_url=canonical_url,
        language=language,
        metadata={"feed_url": feed_url},
    )


def _atom_entry(item: ET.Element, source_id: UUID, feed_url: str) -> SocialDocument | None:
    title = _child_text(item, "title")
    content = _child_text(item, "content") or _child_text(item, "summary")
    text = sanitize_html(" ".join(value for value in (title, content) if value))
    link = None
    for element in _children(item, "link"):
        rel = element.attrib.get("rel", "alternate")
        href = element.attrib.get("href")
        if href and rel == "alternate":
            link = href
            break
    canonical_url = urljoin(feed_url, link) if link else feed_url
    external_id = _child_text(item, "id") or link or _fallback_id(canonical_url, text)
    published = _parse_datetime(
        _child_text(item, "published") or _child_text(item, "updated")
    )
    if published is None:
        return None
    author = next(iter(_children(item, "author")), None)
    author_id = None if author is None else (_child_text(author, "uri") or _child_text(author, "name"))
    language = item.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    return SocialDocument(
        provider=SocialProvider.RSS,
        external_id=external_id,
        source_id=source_id,
        document_kind=SocialDocumentKind.FEED_ENTRY,
        author_external_id=author_id,
        text=text,
        published_at=published,
        canonical_url=canonical_url,
        language=language,
        metadata={"feed_url": feed_url},
    )


def _children(parent: ET.Element, name: str) -> Iterable[ET.Element]:
    normalized_name = name.casefold()
    return (child for child in parent if _local(child.tag) == normalized_name)


def _child_text(parent: ET.Element, name: str) -> str | None:
    normalized_name = name.casefold()
    for child in parent.iter():
        if child is parent or _local(child.tag) != normalized_name:
            continue
        value = "".join(child.itertext()).strip()
        if value:
            return value
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _fallback_id(url: str, text: str) -> str:
    return "sha256:" + hashlib.sha256(f"{url}\n{text}".encode()).hexdigest()
