from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from bs4 import BeautifulSoup

from ...domain import SocialDocument, SocialDocumentKind, SocialProvider


def map_status(status: Mapping[str, object], source_id: UUID) -> SocialDocument | None:
    status_id = status.get("id")
    created = status.get("created_at")
    url = status.get("url") or status.get("uri")
    account = status.get("account")
    if not isinstance(status_id, str) or not isinstance(created, str) or not isinstance(url, str):
        return None
    try:
        published = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
    account_id = account.get("id") if isinstance(account, Mapping) else None
    content = status.get("content")
    text = BeautifulSoup(content if isinstance(content, str) else "", "html.parser").get_text(
        " ", strip=True
    )
    return SocialDocument(
        provider=SocialProvider.MASTODON,
        external_id=status_id,
        source_id=source_id,
        document_kind=SocialDocumentKind.POST,
        author_external_id=account_id if isinstance(account_id, str) else None,
        text=text,
        published_at=published,
        canonical_url=url,
        language=status.get("language") if isinstance(status.get("language"), str) else None,
        metadata={"sensitive": bool(status.get("sensitive", False))},
    )

