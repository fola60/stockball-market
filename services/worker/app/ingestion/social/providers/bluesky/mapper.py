from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping
from uuid import UUID

from ...domain import SocialDocument, SocialDocumentKind, SocialProvider


def map_feed_item(item: Mapping[str, object], source_id: UUID) -> SocialDocument | None:
    # getAuthorFeed wraps reposts with a reason. Original posts are still returned without it.
    if item.get("reason") is not None:
        return None
    post = item.get("post")
    if not isinstance(post, Mapping):
        return None
    record = post.get("record")
    author = post.get("author")
    if not isinstance(record, Mapping) or not isinstance(author, Mapping):
        return None
    uri = _string(post.get("uri"))
    text = _string(record.get("text"))
    created_at = _datetime(record.get("createdAt"))
    did = _string(author.get("did"))
    if not uri or text is None or created_at is None or not did:
        return None
    rkey = uri.rsplit("/", 1)[-1]
    handle = _string(author.get("handle")) or did
    languages = record.get("langs")
    language = (
        str(languages[0])
        if isinstance(languages, list) and languages and isinstance(languages[0], str)
        else None
    )
    metadata: dict[str, object] = {"uri": uri, "cid": _string(post.get("cid")) or ""}
    embed = post.get("embed")
    if isinstance(embed, Mapping):
        record_view = embed.get("record")
        if isinstance(record_view, Mapping):
            quoted_uri = record_view.get("uri")
            if isinstance(quoted_uri, str):
                metadata["quoted_post_uri"] = quoted_uri
    return SocialDocument(
        provider=SocialProvider.BLUESKY,
        external_id=uri,
        source_id=source_id,
        document_kind=SocialDocumentKind.POST,
        author_external_id=did,
        text=text,
        published_at=created_at,
        canonical_url=f"https://bsky.app/profile/{handle}/post/{rkey}",
        language=language,
        metadata=metadata,
    )


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
