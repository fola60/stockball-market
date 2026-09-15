"""Rank active Bluesky community accounts for reviewed social-source curation.

This is a discovery aid, not an ingestion path. It searches public actor profiles, samples each
candidate's latest original posts, and emits JSON lines for an operator to review before seeding
immutable DIDs in a migration.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import certifi

_PUBLIC_API = "https://public.api.bsky.app/xrpc/"
_SEARCH_API = "https://api.bsky.app/xrpc/"
_MATCH_EVENT = re.compile(
    r"(?i)(matchday|kick.?off|half.?time|full.?time|line.?up|starting xi|goal|"
    r"substitut|team news|\bht\b|\bft\b|[0-9]+[’']|#[a-z]{3}[a-z]{3}\b)"
)
_REJECT = re.compile(
    r"(?i)(crypto|\bnft\b|onlyfans|football manager|parody|not (?:an )?official)"
)
_OFFICIAL_DIDS = {
    "did:plc:6mb4szcdermfvwvorc4tfztv",
    "did:plc:jonvi4iruke6hrpofoswvugr",
    "did:plc:lim2lg7owxl6o6r7fnjs7bwn",
    "did:plc:oehqmmuvgd6dyful4fakeaif",
    "did:plc:pdfrjhvbb6r5bxfc27pocimy",
    "did:plc:saw6l6fvyixwgprce7uohrvg",
    "did:plc:zi55hvfbtohpdx7y35viqqma",
    "did:plc:zutenr6tt7vk7qxsqysa3pua",
    "did:plc:zyklbm6a5p3h4qesx524ptgf",
}


@dataclass(frozen=True)
class ClubSearch:
    queries: tuple[str, ...]
    club_pattern: str


CLUBS = {
    "Bournemouth": ClubSearch(
        ("AFC Bournemouth", "AFCB", "Cherries AFCB", "AFCB fan", "AFCB podcast"),
        r"(?i)(\bafcb\b|bournemouth|\bcherries\b)",
    ),
    "Arsenal": ClubSearch(
        ("Arsenal FC", "Gunners Arsenal", "AFC Arsenal"),
        r"(?i)(arsenal|\bgooners?\b|\bgunners?\b)",
    ),
    "Aston Villa": ClubSearch(
        ("Aston Villa", "AVFC", "Villa football"),
        r"(?i)(aston villa|\bavfc\b|\bvilla\b)",
    ),
    "Brentford": ClubSearch(
        ("Brentford FC", "Brentford Bees", "Brentford football", "Brentford fan", "Brentford podcast"),
        r"(?i)(brentford|\bbrentfordfc\b)",
    ),
    "Brighton & Hove Albion": ClubSearch(
        ("Brighton Hove Albion", "BHAFC", "Brighton Seagulls", "BHAFC fan", "BHAFC podcast"),
        r"(?i)(brighton.{0,20}albion|\bbhafc\b|\bseagulls\b)",
    ),
    "Chelsea": ClubSearch(
        ("Chelsea FC", "CFC Chelsea", "Chelsea football", "Chelsea fan", "Chelsea podcast"),
        r"(?i)(chelsea|\bcfc\b)",
    ),
    "Coventry City": ClubSearch(
        ("Coventry City FC", "CCFC Coventry", "Sky Blues Coventry", "CCFC fan", "Coventry City podcast"),
        r"(?i)(coventry city|\bccfc\b|\bpusb\b|sky blues)",
    ),
    "Crystal Palace": ClubSearch(
        ("Crystal Palace FC", "CPFC Palace", "Palace Eagles", "CPFC fan", "Crystal Palace podcast"),
        r"(?i)(crystal palace|\bcpfc\b)",
    ),
    "Everton": ClubSearch(
        ("Everton FC", "EFC Everton", "Everton Toffees"),
        r"(?i)(everton|\befc\b|\btoffees\b)",
    ),
    "Fulham": ClubSearch(
        ("Fulham FC", "FFC Fulham", "Fulham Cottagers", "Fulham fan", "Fulham podcast"),
        r"(?i)(fulham|\bffc\b|\bcottagers\b)",
    ),
    "Hull City": ClubSearch(
        ("Hull City AFC", "HCAFC", "Hull City Tigers", "HCAFC fan", "Hull City podcast"),
        r"(?i)(hull city|\bhcafc\b)",
    ),
    "Ipswich Town": ClubSearch(
        ("Ipswich Town FC", "ITFC Ipswich", "Tractor Boys Ipswich"),
        r"(?i)(ipswich town|\bitfc\b|tractor boys)",
    ),
    "Leeds United": ClubSearch(
        ("Leeds United FC", "LUFC Leeds", "Leeds football"),
        r"(?i)(leeds united|\blufc\b)",
    ),
    "Liverpool": ClubSearch(
        ("Liverpool FC", "LFC Liverpool", "Liverpool football"),
        r"(?i)(liverpool|\blfc\b)",
    ),
    "Manchester City": ClubSearch(
        ("Manchester City FC", "MCFC Man City", "Man City football", "MCFC fan", "Manchester City podcast", "City Xtra", "#MCFC"),
        r"(?i)(manchester city|\bman city\b|\bmcfc\b)",
    ),
    "Manchester United": ClubSearch(
        ("Manchester United FC", "MUFC Man United", "Man Utd football", "MUFC fan", "Manchester United podcast", "United We Stand"),
        r"(?i)(manchester united|\bman utd\b|\bmufc\b)",
    ),
    "Newcastle United": ClubSearch(
        ("Newcastle United FC", "NUFC Newcastle", "Newcastle Magpies"),
        r"(?i)(newcastle united|\bnufc\b)",
    ),
    "Nottingham Forest": ClubSearch(
        ("Nottingham Forest FC", "NFFC Forest", "Forest football", "NFFC fan", "Nottingham Forest podcast", "Tricky Trees", "#NFFC"),
        r"(?i)(nottingham forest|\bnffc\b)",
    ),
    "Sunderland": ClubSearch(
        ("Sunderland AFC", "SAFC Sunderland", "Black Cats Sunderland"),
        r"(?i)(sunderland|\bsafc\b)",
    ),
    "Tottenham Hotspur": ClubSearch(
        ("Tottenham Hotspur FC", "THFC Spurs", "Tottenham Spurs"),
        r"(?i)(tottenham|\bthfc\b|\bspurs\b)",
    ),
}


@dataclass(frozen=True)
class Candidate:
    club: str
    handle: str
    did: str
    display_name: str
    description: str
    latest_post_at: str
    recent_posts: int
    club_posts: int
    live_match_posts: int
    score: int


def _get(path: str, params: dict[str, object]) -> dict[str, Any]:
    context = ssl.create_default_context(cafile=certifi.where())
    base_url = _SEARCH_API if path == "app.bsky.feed.searchPosts" else _PUBLIC_API
    url = base_url + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "StockballSourceAudit/1.0"})
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            return json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return {}


def _search(search: ClubSearch) -> dict[str, dict[str, Any]]:
    actors: dict[str, dict[str, Any]] = {}
    for query in search.queries:
        for actor in _get("app.bsky.actor.searchActors", {"q": query, "limit": 100}).get(
            "actors", []
        ):
            actors[str(actor["did"])] = actor
        # Actor search favours prominent profiles and misses many active match-day posters.
        # Recent post search supplies their author profiles without accepting the posts as
        # evidence on its own; _rank still applies the full profile and activity checks.
        for item in _get(
            "app.bsky.feed.searchPosts",
            {
                "q": query,
                "limit": 100,
                "sort": "latest",
                "since": (datetime.now(UTC) - timedelta(days=90)).isoformat(),
            },
        ).get("posts", []):
            actor = item.get("author", {})
            if actor.get("did") and actor.get("handle"):
                actors[str(actor["did"])] = actor
    return actors


def _rank(club: str, search: ClubSearch, actor: dict[str, Any]) -> Candidate | None:
    if actor["did"] in _OFFICIAL_DIDS:
        return None
    pattern = re.compile(search.club_pattern)
    profile = " ".join(
        str(actor.get(key) or "") for key in ("handle", "displayName", "description")
    )
    if not pattern.search(profile) or _REJECT.search(profile):
        return None
    payload = _get(
        "app.bsky.feed.getAuthorFeed",
        {"actor": actor["did"], "limit": 100, "filter": "posts_no_replies"},
    )
    now = datetime.now(UTC)
    posts: list[tuple[datetime, str]] = []
    for item in payload.get("feed", []):
        post = item.get("post", {})
        if item.get("reason") is not None or post.get("author", {}).get("did") != actor["did"]:
            continue
        record = post.get("record", {})
        text = str(record.get("text") or "")
        try:
            created_at = datetime.fromisoformat(str(record["createdAt"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        posts.append((created_at, text))
    if not posts:
        return None
    latest = max(created_at for created_at, _ in posts)
    recent = [post for post in posts if post[0] >= now - timedelta(days=90)]
    club_posts = [post for post in recent if pattern.search(post[1])]
    live_posts = [post for post in club_posts if _MATCH_EVENT.search(post[1])]
    if latest < now - timedelta(days=30) or len(recent) < 8:
        return None
    score = (
        min(len(club_posts), 40) * 4
        + min(len(live_posts), 20) * 5
        + min(len(recent), 40)
        + (20 if latest >= now - timedelta(days=7) else 0)
    )
    return Candidate(
        club=club,
        handle=str(actor["handle"]),
        did=str(actor["did"]),
        display_name=str(actor.get("displayName") or ""),
        description=str(actor.get("description") or "").replace("\n", " ")[:240],
        latest_post_at=latest.isoformat(),
        recent_posts=len(recent),
        club_posts=len(club_posts),
        live_match_posts=len(live_posts),
        score=score,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--club", action="append", choices=sorted(CLUBS))
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    selected = args.club or list(CLUBS)
    for club in selected:
        search = CLUBS[club]
        actors = _search(search)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(_rank, club, search, actor) for actor in actors.values()]
            candidates = [candidate for future in futures if (candidate := future.result())]
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        print(json.dumps({"club": club, "eligible": len(candidates)}))
        for candidate in candidates[: args.limit]:
            payload = asdict(candidate)
            if args.compact:
                payload = {
                    key: payload[key]
                    for key in (
                        "club",
                        "handle",
                        "did",
                        "recent_posts",
                        "club_posts",
                        "live_match_posts",
                    )
                }
            print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
