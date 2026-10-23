from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

TEAM_INDEX_KIND = "TEAM"
# Fewer listed players than a starting eleven means a partial ingestion, not a squad.
MIN_TEAM_PLAYERS = 11
# One unit of a team fund holds one share of every player in the squad, so the unit price is
# the squad's total share price and pricier players carry more weight.
TEAM_SHARES_PER_UNIT = "1"
# A fund holding at least this share of its value as cash, after a buyout, is rebalanced to
# reinvest it. Rebalances leave a sliver of cash behind, which is too small to be worth trading.
CASH_REINVEST_SHARE = 0.01

# Conventional three-letter codes, keyed by normalized club name. Player ingestion has used
# several providers' short names ("Manchester Utd", "Nott'ham Forest", "Nottingham",
# "Newcastle"); full names are listed too.
CLUB_CODES = {
    "arsenal": "ARS",
    "aston villa": "AVL",
    "bournemouth": "BOU",
    "afc bournemouth": "BOU",
    "brentford": "BRE",
    "brighton": "BHA",
    "brighton and hove albion": "BHA",
    "burnley": "BUR",
    "chelsea": "CHE",
    "coventry city": "COV",
    "crystal palace": "CRY",
    "everton": "EVE",
    "fulham": "FUL",
    "hull city": "HUL",
    "ipswich town": "IPS",
    "leeds united": "LEE",
    "leicester city": "LEI",
    "liverpool": "LIV",
    "luton town": "LUT",
    "manchester city": "MCI",
    "manchester utd": "MUN",
    "manchester united": "MUN",
    "newcastle": "NEW",
    "newcastle utd": "NEW",
    "newcastle united": "NEW",
    "nottingham": "NFO",
    "nottham forest": "NFO",
    "nottingham forest": "NFO",
    "sheffield utd": "SHU",
    "sheffield united": "SHU",
    "southampton": "SOU",
    "sunderland": "SUN",
    "tottenham": "TOT",
    "tottenham hotspur": "TOT",
    "west ham": "WHU",
    "west ham united": "WHU",
    "wolves": "WOL",
    "wolverhampton wanderers": "WOL",
}


def _normalized(club: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", club).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z ]", "", ascii_name.lower().replace("&", "and")).split())


def club_code(club: str) -> str:
    """A club's three-letter code, or the first three letters of an unknown club's name."""
    known = CLUB_CODES.get(_normalized(club))
    if known:
        return known
    letters = re.sub(r"[^A-Z]", "", _normalized(club).upper())
    return (letters[:3] or "IDX").ljust(3, "X")


def team_fund_symbol(club: str) -> str:
    return f"IDX-{club_code(club)}"


def team_fund_name(club: str) -> str:
    return f"{club} Index"


@dataclass(frozen=True)
class TeamRoster:
    """The team rule's result for one club: its current-season players who can trade."""

    club: str
    instrument_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class TeamFund:
    """A listed team fund and its basket as it stands."""

    instrument_id: UUID
    symbol: str
    club: str
    members: frozenset[UUID]
    # Members halted for anything but a match day: players waiting for their buyout. A
    # rebalance cannot sell them, so they stay until delisting turns them into cash.
    halted_members: frozenset[UUID] = frozenset()
    # Cash behind each unit and what a unit is worth, as decimal strings.
    cash_per_unit: str = "0"
    unit_price: str = "0"

    @property
    def cash_share(self) -> float:
        """The part of a unit's value held as cash."""
        price = float(self.unit_price)
        return float(self.cash_per_unit) / price if price > 0 else 0.0


class ReviewAction(StrEnum):
    CREATED = "CREATED"
    REBALANCED = "REBALANCED"
    UNCHANGED = "UNCHANGED"
    FAILED = "FAILED"
    # Dry runs.
    WOULD_CREATE = "WOULD_CREATE"
    WOULD_REBALANCE = "WOULD_REBALANCE"


@dataclass(frozen=True)
class FundReview:
    club: str
    symbol: str
    action: ReviewAction
    constituent_count: int
    added: tuple[UUID, ...] = ()
    removed: tuple[UUID, ...] = ()
    instrument_id: UUID | None = None
    unit_price: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class IndexReviewResult:
    season: int
    dry_run: bool
    reviews: tuple[FundReview, ...] = ()
    # Clubs without a fund left out because too few of their players are listed.
    too_small: dict[str, int] = field(default_factory=dict)
    # Funds whose club has no listed players this season, e.g. after relegation.
    without_roster: tuple[str, ...] = ()

    def count(self, *actions: ReviewAction) -> int:
        return sum(1 for review in self.reviews if review.action in actions)
