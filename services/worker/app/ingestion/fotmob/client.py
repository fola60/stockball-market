"""Public FotMob fixture pages and match documents, with a resumable disk archive."""

from __future__ import annotations

import json
import math
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.fotmob.com"
IMAGE_BASE_URL = "https://images.fotmob.com/image_resources/playerimages"
TEAM_LOGO_BASE_URL = "https://images.fotmob.com/image_resources/logo/teamlogo"
MAX_IMAGE_BYTES = 1048576


class FotMobError(ValueError):
    pass


class FotMobImageMissing(FotMobError):
    pass


@dataclass(frozen=True)
class FotMobImage:
    source_url: str
    data: bytes
    width: int
    height: int


def page_props(body: str) -> dict:
    node = BeautifulSoup(body, "html.parser").find("script", id="__NEXT_DATA__")
    if node is None or node.string is None:
        raise FotMobError("FotMob page has no structured data")
    return json.loads(node.string)["props"]["pageProps"]


class FotMobClient:
    def __init__(self, *, interval_seconds: float = 2.0, archive_dir: Path | None = None):
        if not math.isfinite(interval_seconds) or interval_seconds < 0:
            raise ValueError("request interval must be nonnegative")
        self.interval_seconds = interval_seconds
        self.archive_dir = archive_dir
        self._last_request = 0.0
        self._http = httpx.Client(timeout=45, follow_redirects=True)

    def close(self):
        self._http.close()

    def _get(self, url: str) -> str:
        time.sleep(max(0, self.interval_seconds - (time.monotonic() - self._last_request)))
        try:
            response = self._http.get(url)
            response.raise_for_status()
            return response.text
        finally:
            self._last_request = time.monotonic()

    def fixtures(self, league: int, season: int) -> tuple[str, str, list[dict]]:
        url = f"{BASE_URL}/leagues/{league}/fixtures?season={season}-{season + 1}"
        body = self._get(url)
        props = page_props(body)
        details = props.get("details", {})
        if (
            str(details.get("id")) != str(league)
            or details.get("selectedSeason") != f"{season}/{season + 1}"
        ):
            raise FotMobError(f"FotMob returned the wrong league/season for {league}/{season}")
        matches = props.get("fixtures", {}).get("allMatches")
        if not isinstance(matches, list) or not matches:
            raise FotMobError("FotMob returned no season fixtures")
        ids = [str(match["id"]) for match in matches]
        if len(set(ids)) != len(ids):
            raise FotMobError("Duplicate match IDs in FotMob season")
        return url, body, matches

    def match(self, match_id: str, *, refresh: bool = False) -> tuple[str, str, dict]:
        if not match_id.isdigit():
            raise FotMobError("Invalid FotMob match ID")
        url = f"{BASE_URL}/api/data/matchDetails?matchId={match_id}"
        path = self.archive_dir / f"{match_id}.json" if self.archive_dir else None
        body = path.read_text() if path and path.exists() and not refresh else self._get(url)
        data = json.loads(body)
        if str(data.get("general", {}).get("matchId")) != match_id:
            raise FotMobError(f"FotMob returned a different match for {match_id}")
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(body)
            temporary.replace(path)
        return url, body, data

    def player_profile(self, player_id: str) -> tuple[str, str, dict]:
        if not player_id.isdigit():
            raise FotMobError("Invalid FotMob player ID")
        url = f"{BASE_URL}/players/{player_id}"
        body = self._get(url)
        data = page_props(body).get("data", {})
        if str(data.get("id")) != player_id:
            raise FotMobError(f"FotMob returned a different player for {player_id}")
        return url, body, data

    def player_image(self, player_id: str) -> FotMobImage:
        if not player_id.isdigit():
            raise FotMobError("Invalid FotMob player ID")
        return self._png(f"{IMAGE_BASE_URL}/{player_id}.png", f"portrait for player {player_id}")

    def team_logo(self, team_id: str) -> FotMobImage:
        if not team_id.isdigit():
            raise FotMobError("Invalid FotMob team ID")
        return self._png(f"{TEAM_LOGO_BASE_URL}/{team_id}.png", f"logo for team {team_id}")

    def _png(self, url: str, label: str) -> FotMobImage:
        time.sleep(max(0, self.interval_seconds - (time.monotonic() - self._last_request)))
        try:
            with self._http.stream("GET", url) as response:
                if response.status_code in (403, 404):
                    raise FotMobImageMissing(f"No FotMob {label}")
                response.raise_for_status()
                if response.url.host != "images.fotmob.com":
                    raise FotMobError(f"FotMob {label} redirected to another host")
                if response.headers.get("content-type", "").split(";", 1)[0].strip() != "image/png":
                    raise FotMobError(f"FotMob {label} has an unexpected content type")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise FotMobError(f"FotMob {label} exceeds the size limit")
                    chunks.append(chunk)
                data = b"".join(chunks)
        finally:
            self._last_request = time.monotonic()
        if len(data) < 45 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[-8:-4] != b"IEND":
            raise FotMobError(f"FotMob {label} is not a complete PNG")
        width, height = struct.unpack(">II", data[16:24])
        if not (1 <= width <= 4096 and 1 <= height <= 4096):
            raise FotMobError(f"FotMob {label} has invalid dimensions")
        return FotMobImage(url, data, width, height)


def match_page_url(match: dict) -> str:
    url = urljoin(BASE_URL, match["pageUrl"])
    if urlparse(url).hostname != "www.fotmob.com":
        raise FotMobError("Unexpected match URL host")
    return url
