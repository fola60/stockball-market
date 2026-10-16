from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from uuid import UUID

TEAM_INDEX_KIND = "TEAM"
# Fewer listed players than a starting eleven means a partial ingestion, not a squad.
MIN_TEAM_PLAYERS = 11
# One unit of a team fund holds one share of every player in the squad, so the unit price is
# the squad's total share price and pricier players carry more weight.
TEAM_SHARES_PER_UNIT = "1"

# Conventional three-letter codes, keyed by normalized club name. Player ingestion uses
# FBref's short names ("Manchester Utd", "Nott'ham Forest"); full names are listed too.
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
    "crystal palace": "CRY",
    "everton": "EVE",
    "fulham": "FUL",
    "ipswich town": "IPS",
    "leeds united": "LEE",
    "leicester city": "LEI",
    "liverpool": "LIV",
    "luton town": "LUT",
    "manchester city": "MCI",
    "manchester utd": "MUN",
    "manchester united": "MUN",
    "newcastle utd": "NEW",
    "newcastle united": "NEW",
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
    club: str
    instrument_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class TeamIndexFundOutcome:
    club: str
    symbol: str
    constituent_count: int
    # None on a dry run.
    created: bool | None = None
    instrument_id: UUID | None = None
    unit_price: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class TeamIndexFundsResult:
    season: int
    dry_run: bool
    outcomes: tuple[TeamIndexFundOutcome, ...] = ()
    # Clubs that already have a team fund, by symbol.
    existing: dict[str, str] = field(default_factory=dict)
    # Clubs left out because too few of their players are listed, with the count found.
    too_small: dict[str, int] = field(default_factory=dict)

    @property
    def created_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.created)

    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.error is not None)
