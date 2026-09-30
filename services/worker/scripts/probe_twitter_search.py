"""Quick local test: search X and print parsed tweets.

Usage:
    python3 -m scripts.probe_twitter_search "man united injury"
    python3 -m scripts.probe_twitter_search "arsenal confirmed XI" --user-data-dir /path/to/chrome

Requires:
    - Chrome installed (for browser fallback)
    - Logged-in X session in Stockball's dedicated Chrome profile
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.ingestion.social.twitter.client import TwitterIngestionError, TwitterRecentSearchClient
from scripts.open_chrome_profile import (
    DEFAULT_WORKER_CHROME_USER_DATA_DIR,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search X with a dedicated Chrome profile")
    parser.add_argument("query", nargs="?", default="man united injury")
    parser.add_argument("--profile", help="profile directory; default: Default")
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        help="explicit Chrome root; default: Stockball's dedicated browser directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    user_data_dir = args.user_data_dir or DEFAULT_WORKER_CHROME_USER_DATA_DIR
    user_data_dir.mkdir(parents=True, exist_ok=True)
    profile = args.profile or "Default"

    print(f"Searching: {args.query}\n")
    print(f"Using Chrome profile: {profile} ({user_data_dir})\n")

    client = TwitterRecentSearchClient(
        policy_acknowledged=True,
        browser_enabled=True,
        request_interval_seconds=2.0,
        browser_idle_seconds=5.0,
        browser_user_data_dir=str(user_data_dir),
        browser_profile_directory=profile,
    )

    try:
        page = client.search_page(args.query)
    except TwitterIngestionError as exc:
        print(f"Twitter search failed: {exc}", file=sys.stderr)
        cause = exc.__cause__
        if cause is not None:
            print(f"Cause: {cause}", file=sys.stderr)
        return 1

    print(f"Found {len(page.posts)} posts\n")
    for i, post in enumerate(page.posts, 1):
        print(f"{i}. @{post.author_id}  ({post.created_at.strftime('%Y-%m-%d %H:%M')})")
        print(f"   {post.text}")
        print(f"   post_id={post.post_id}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
