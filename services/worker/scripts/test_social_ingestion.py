"""Fetch and print normalized social documents without persisting them.

Usage:
    python3 -m scripts.test_social_ingestion bluesky did:plc:example
    python3 -m scripts.test_social_ingestion rss https://example.com/feed.xml
    python3 -m scripts.test_social_ingestion mastodon https://mastodon.social 123456

The script calls the same provider connectors used by the worker. Sources must already
be reviewed before using their output operationally; this command is diagnostics only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from uuid import uuid4

from app.ingestion.social import (
    BlueskyConnector,
    IngestionCursor,
    MastodonConnector,
    PollResult,
    RssConnector,
    SocialIngestionError,
    SocialProvider,
    SocialSubscription,
    SocialSubscriptionMode,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch social content through the worker's provider-neutral connectors"
    )
    parser.add_argument(
        "--full-text",
        action="store_true",
        help="print complete normalized text instead of truncating it",
    )
    subparsers = parser.add_subparsers(dest="provider", required=True)

    bluesky = subparsers.add_parser("bluesky", help="poll a public Bluesky author feed")
    bluesky.add_argument("did", help="reviewed Bluesky DID, for example did:plc:...")
    bluesky.add_argument("--cursor", help="optional provider pagination cursor")
    bluesky.add_argument("--limit", type=_positive_int, default=25)

    rss = subparsers.add_parser("rss", help="poll an approved RSS 2.0 or Atom feed")
    rss.add_argument("url", help="approved HTTP(S) feed URL")
    rss.add_argument(
        "--approved-redirect-host",
        action="append",
        default=[],
        help="additional reviewed redirect host; may be repeated",
    )
    rss.add_argument("--etag", help="optional ETag validator from an earlier run")
    rss.add_argument("--last-modified", help="optional Last-Modified validator")
    rss.add_argument("--limit", type=_positive_int, default=25)

    mastodon = subparsers.add_parser(
        "mastodon", help="poll a public Mastodon account timeline"
    )
    mastodon.add_argument("instance_url", help="HTTPS instance origin")
    mastodon.add_argument("account_id", help="stable account ID on that instance")
    mastodon.add_argument("--since-id", help="optional status cursor from an earlier run")
    mastodon.add_argument("--limit", type=_positive_int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = asyncio.run(_poll(args))
    except (SocialIngestionError, OSError, ValueError) as error:
        print(f"Social ingestion test failed: {error}", file=sys.stderr)
        if error.__cause__ is not None:
            print(f"Cause: {error.__cause__}", file=sys.stderr)
        return 1

    _print_result(result, full_text=args.full_text)
    return 0


async def _poll(args: argparse.Namespace) -> PollResult:
    source_id = uuid4()
    subscription_id = uuid4()
    cursor: IngestionCursor | None = None

    if args.provider == "bluesky":
        connector = BlueskyConnector(page_size=args.limit)
        subscription = SocialSubscription(
            id=subscription_id,
            source_id=source_id,
            provider=SocialProvider.BLUESKY,
            mode=SocialSubscriptionMode.AUTHOR_FEED,
            configuration={"did": args.did},
            polling_interval=timedelta(minutes=5),
        )
        if args.cursor:
            cursor = IngestionCursor(subscription_id, cursor={"cursor": args.cursor})
    elif args.provider == "rss":
        connector = RssConnector(max_items=args.limit)
        subscription = SocialSubscription(
            id=subscription_id,
            source_id=source_id,
            provider=SocialProvider.RSS,
            mode=SocialSubscriptionMode.RSS_FEED,
            configuration={
                "url": args.url,
                "approved_redirect_hosts": args.approved_redirect_host,
            },
            polling_interval=timedelta(minutes=15),
        )
        if args.etag or args.last_modified:
            cursor = IngestionCursor(
                subscription_id,
                etag=args.etag,
                last_modified=args.last_modified,
            )
    else:
        connector = MastodonConnector(page_size=args.limit)
        subscription = SocialSubscription(
            id=subscription_id,
            source_id=source_id,
            provider=SocialProvider.MASTODON,
            mode=SocialSubscriptionMode.AUTHOR_FEED,
            configuration={
                "instance_url": args.instance_url,
                "account_id": args.account_id,
            },
            polling_interval=timedelta(minutes=5),
        )
        if args.since_id:
            cursor = IngestionCursor(subscription_id, cursor={"since_id": args.since_id})

    return await connector.poll(subscription, cursor)


def _print_result(result: PollResult, *, full_text: bool) -> None:
    print(f"Found {len(result.documents)} normalized documents\n")
    for index, document in enumerate(result.documents, 1):
        text = document.text if full_text else _truncate(document.text, 300)
        print(f"{index}. [{document.provider.value}] {document.published_at.isoformat()}")
        if document.author_external_id:
            print(f"   author={document.author_external_id}")
        print(f"   external_id={document.external_id}")
        print(f"   url={document.canonical_url}")
        print(f"   text={text}")
        print()

    if result.next_cursor is not None:
        print(f"Next cursor: {json.dumps(dict(result.next_cursor), sort_keys=True)}")
    if result.rate_limit is not None:
        reset_at = result.rate_limit.reset_at
        print(
            "Rate limit: "
            f"remaining={result.rate_limit.remaining} "
            f"limit={result.rate_limit.limit} "
            f"reset_at={None if reset_at is None else reset_at.isoformat()}"
        )
    if result.retry_after is not None:
        print(f"Retry after: {result.retry_after.total_seconds():g} seconds")


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
