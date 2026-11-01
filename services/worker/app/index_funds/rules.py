"""Rule index funds: funds whose members come from a league-wide rule.

Each definition says who is eligible (club, position, nationality, age, minutes) and, for
ranked funds, what they are ranked by and how many are held. Ranked funds have a buffer: a
member stays until it falls a few places outside the cut-off, and a newcomer must climb a few
places inside it, so a player hovering at the line does not trade in and out every review.

Rankings use measures from outside the market (Transfermarkt values, season stats, ratings,
bookmakers' odds, social mentions), never Stockball's own price: a fund buying a player
raises that player's price, which would keep them in the fund.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from uuid import UUID

from .models import club_code

RULE_INDEX_KIND = "RULE"
# New rule funds list at this unit price, so funds of any size start comparable.
LAUNCH_UNIT_PRICE = Decimal("100")
SHARES_QUANTUM = Decimal("0.000001")
# An equal-value fund is re-levelled at its review once a member's weight drifts this far from
# an equal share, relative to that share.
EQUAL_VALUE_DRIFT = 0.25
# Data older than this, relative to the newest in its source, no longer counts: a player whose
# latest odds are from a fixture weeks ago is not among the next matchday's favourites.
ODDS_WINDOW_DAYS = 7
SOCIAL_WINDOW_DAYS = 2


class Weighting(StrEnum):
    EQUAL_SHARES = "EQUAL_SHARES"
    EQUAL_VALUE = "EQUAL_VALUE"


class Metric(StrEnum):
    # Transfermarkt value, or the share's seed price where a player has none.
    VALUATION = "VALUATION"
    NON_PENALTY_GOALS = "NON_PENALTY_GOALS"
    # Chances created (passes leading to a shot) per 90 minutes.
    CREATIVITY = "CREATIVITY"
    # FotMob rating over the last five rated appearances.
    RECENT_RATING = "RECENT_RATING"
    # Bookmakers' implied probability of scoring in the player's next fixture.
    GOALSCORER_ODDS = "GOALSCORER_ODDS"
    # Trusted mentions over the past week, scaled by their sentiment.
    SOCIAL_BUZZ = "SOCIAL_BUZZ"
    KEEPER_MINUTES = "KEEPER_MINUTES"
    MINUTES = "MINUTES"


class ClubSet(StrEnum):
    # Clubs in this season's league that were not in last season's.
    PROMOTED = "PROMOTED"


SOUTH_AMERICA = frozenset({"ARG", "BOL", "BRA", "CHI", "COL", "ECU", "PAR", "PER", "URU", "VEN"})


@dataclass(frozen=True)
class PlayerFacts:
    """What the rules know about one listed, current-season player who can trade."""

    instrument_id: UUID
    club: str
    price: Decimal
    position: str | None = None
    age: int | None = None
    nationality: str | None = None
    valuation: float | None = None
    minutes: int = 0
    games: int = 0
    non_penalty_goals: int = 0
    assists: int = 0
    chances_created: int = 0
    keeper_minutes: int = 0
    recent_rating: float | None = None
    rated_appearances: int = 0
    goalscorer_probability: float | None = None
    social_mentions: int | None = None
    social_sentiment: float | None = None


@dataclass(frozen=True)
class LeagueFacts:
    season: int
    players: tuple[PlayerFacts, ...]
    # Clubs whose players appear in last season's stats; empty when that season is missing.
    previous_season_clubs: frozenset[str] = frozenset()

    def club_matches(self) -> dict[str, int]:
        """League matches each club has played: the most any of its players has appeared in."""
        matches: dict[str, int] = {}
        for player in self.players:
            key = club_code(player.club)
            matches[key] = max(matches.get(key, 0), player.games)
        return matches

    def promoted_clubs(self) -> frozenset[str]:
        if not self.previous_season_clubs:
            return frozenset()
        previous = {club_code(club) for club in self.previous_season_clubs}
        return frozenset(
            club_code(p.club) for p in self.players if club_code(p.club) not in previous
        )


@dataclass(frozen=True)
class Eligibility:
    # Three-letter club codes.
    clubs: frozenset[str] | None = None
    club_set: ClubSet | None = None
    # Primary positions: GK, DF, MF or FW.
    positions: frozenset[str] | None = None
    nationalities: frozenset[str] | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_minutes: int = 0
    # Share of the club's league minutes the player has played.
    min_minutes_share: float = 0.0
    min_rated_appearances: int = 0


@dataclass(frozen=True)
class RuleFundDefinition:
    key: str
    symbol: str
    name: str
    category: str
    description: str
    eligibility: Eligibility = field(default_factory=Eligibility)
    # None holds every eligible player.
    rank_by: Metric | None = None
    size: int | None = None
    # Ranks start here, so a fund can hold the 101st to 200th.
    rank_from: int = 1
    buffer: int = 0
    # Hold only the top-ranked eligible player at each club.
    one_per_club: bool = False
    weighting: Weighting = Weighting.EQUAL_SHARES
    review_days: int = 1
    min_members: int = 5

    def rule(self) -> dict:
        """The rule as stored with the fund, for its page."""
        stored = asdict(self)
        for name in ("key", "symbol", "name", "category", "description"):
            stored.pop(name)
        eligibility = {
            name: sorted(value) if isinstance(value, frozenset) else value
            for name, value in stored.pop("eligibility").items()
            if value not in (None, 0, 0.0)
        }
        return {"eligibility": eligibility, **stored}


_BIG_SIX = frozenset({"ARS", "CHE", "LIV", "MCI", "MUN", "TOT"})
_LONDON = frozenset({"ARS", "BRE", "CHE", "CRY", "FUL", "TOT", "WHU"})

RULE_FUNDS: tuple[RuleFundDefinition, ...] = (
    # Market
    RuleFundDefinition(
        key="SB20", symbol="IDX-SB20", name="Stockball 20", category="Market",
        description="The 20 most valuable players in the league.",
        rank_by=Metric.VALUATION, size=20, buffer=2, review_days=30, min_members=20,
    ),
    RuleFundDefinition(
        key="SB100", symbol="IDX-SB100", name="Stockball 100", category="Market",
        description="The 100 most valuable players in the league.",
        rank_by=Metric.VALUATION, size=100, buffer=10, review_days=30, min_members=100,
    ),
    RuleFundDefinition(
        key="NEXT100", symbol="IDX-NXT", name="Next 100", category="Market",
        description="The 101st to 200th most valuable players.",
        rank_by=Metric.VALUATION, rank_from=101, size=100, buffer=10, review_days=30,
        min_members=100,
    ),
    # Club groups
    RuleFundDefinition(
        key="BIG6", symbol="IDX-BIG6", name="Big Six", category="Club groups",
        description="Arsenal, Chelsea, Liverpool, both Manchester clubs and Tottenham.",
        eligibility=Eligibility(clubs=_BIG_SIX), min_members=60,
    ),
    RuleFundDefinition(
        key="LONDON", symbol="IDX-LDN", name="London", category="Club groups",
        description="Every London club in the league.",
        eligibility=Eligibility(clubs=_LONDON), min_members=40,
    ),
    RuleFundDefinition(
        key="PROMOTED", symbol="IDX-PRO", name="Promoted", category="Club groups",
        description="The clubs that came up last season.",
        eligibility=Eligibility(club_set=ClubSet.PROMOTED), min_members=11,
    ),
    # Positions
    RuleFundDefinition(
        key="FORWARDS", symbol="IDX-FWD", name="Strikers", category="Positions",
        description="The 15 most valuable forwards.",
        eligibility=Eligibility(positions=frozenset({"FW"})),
        rank_by=Metric.VALUATION, size=15, buffer=2, review_days=30, min_members=15,
    ),
    RuleFundDefinition(
        key="MIDFIELDERS", symbol="IDX-MID", name="Engine Room", category="Positions",
        description="The 15 most valuable midfielders.",
        eligibility=Eligibility(positions=frozenset({"MF"})),
        rank_by=Metric.VALUATION, size=15, buffer=2, review_days=30, min_members=15,
    ),
    RuleFundDefinition(
        key="DEFENDERS", symbol="IDX-DEF", name="Back Line", category="Positions",
        description="The 15 most valuable defenders.",
        eligibility=Eligibility(positions=frozenset({"DF"})),
        rank_by=Metric.VALUATION, size=15, buffer=2, review_days=30, min_members=15,
    ),
    RuleFundDefinition(
        key="KEEPERS", symbol="IDX-GK", name="Number Ones", category="Positions",
        description="Every club's first-choice goalkeeper.",
        eligibility=Eligibility(positions=frozenset({"GK"})),
        rank_by=Metric.KEEPER_MINUTES, one_per_club=True, min_members=10,
    ),
    # People
    RuleFundDefinition(
        key="ENGLAND", symbol="IDX-ENG", name="Three Lions", category="Nationality and age",
        description="The 25 most valuable English players.",
        eligibility=Eligibility(nationalities=frozenset({"ENG"})),
        rank_by=Metric.VALUATION, size=25, buffer=3, review_days=30, min_members=25,
    ),
    RuleFundDefinition(
        key="SOUTH_AMERICA", symbol="IDX-SAM", name="South America",
        category="Nationality and age",
        description="Every South American player in the league.",
        eligibility=Eligibility(nationalities=SOUTH_AMERICA), review_days=30, min_members=10,
    ),
    RuleFundDefinition(
        key="UNDER_21", symbol="IDX-U21", name="Wonderkids", category="Nationality and age",
        description="The 20 most valuable players aged 21 or under who play at least half "
        "their club's minutes.",
        eligibility=Eligibility(max_age=21, min_minutes_share=0.5),
        rank_by=Metric.VALUATION, size=20, buffer=2, weighting=Weighting.EQUAL_VALUE,
        review_days=30, min_members=10,
    ),
    RuleFundDefinition(
        key="OVER_32", symbol="IDX-VET", name="Old Guard", category="Nationality and age",
        description="Players aged 32 or over who play at least half their club's minutes.",
        eligibility=Eligibility(min_age=32, min_minutes_share=0.5),
        weighting=Weighting.EQUAL_VALUE, review_days=30, min_members=5,
    ),
    # Performance
    RuleFundDefinition(
        key="GOLDEN_BOOT", symbol="IDX-GLD", name="Golden Boot", category="Performance",
        description="The league's top 10 scorers, penalties excluded.",
        rank_by=Metric.NON_PENALTY_GOALS, size=10, buffer=1,
        weighting=Weighting.EQUAL_VALUE, review_days=7, min_members=10,
    ),
    RuleFundDefinition(
        key="CREATORS", symbol="IDX-CRE", name="Creators", category="Performance",
        description="The 15 players creating the most chances per 90, from those who play "
        "at least half their club's minutes.",
        eligibility=Eligibility(min_minutes_share=0.5),
        rank_by=Metric.CREATIVITY, size=15, buffer=2,
        weighting=Weighting.EQUAL_VALUE, review_days=7, min_members=15,
    ),
    RuleFundDefinition(
        key="IRON_MEN", symbol="IDX-IRN", name="Iron Men", category="Performance",
        description="The 30 players with the most league minutes, from those who have played "
        "90% of their club's.",
        eligibility=Eligibility(min_minutes_share=0.9),
        rank_by=Metric.MINUTES, size=30, buffer=3,
        weighting=Weighting.EQUAL_VALUE, review_days=7, min_members=30,
    ),
    RuleFundDefinition(
        key="IN_FORM", symbol="IDX-FRM", name="In Form", category="Performance",
        description="The 15 best FotMob ratings over each player's last five appearances.",
        eligibility=Eligibility(min_rated_appearances=3),
        rank_by=Metric.RECENT_RATING, size=15, buffer=2,
        weighting=Weighting.EQUAL_VALUE, review_days=7, min_members=15,
    ),
    # Signals
    RuleFundDefinition(
        key="BOOKIES", symbol="IDX-ODD", name="Bookies' Favourites", category="Signals",
        description="The 15 players bookmakers most expect to score in their next match.",
        rank_by=Metric.GOALSCORER_ODDS, size=15, buffer=2,
        weighting=Weighting.EQUAL_VALUE, review_days=7, min_members=15,
    ),
    RuleFundDefinition(
        key="BUZZ", symbol="IDX-BUZ", name="Buzz", category="Signals",
        description="The 15 most talked-about players this week, weighed by sentiment.",
        rank_by=Metric.SOCIAL_BUZZ, size=15, buffer=2,
        weighting=Weighting.EQUAL_VALUE, review_days=7, min_members=15,
    ),
)


def is_eligible(definition: RuleFundDefinition, player: PlayerFacts, league: LeagueFacts,
                *, club_matches: dict[str, int], promoted: frozenset[str]) -> bool:
    rule = definition.eligibility
    code = club_code(player.club)
    if rule.clubs is not None and code not in rule.clubs:
        return False
    if rule.club_set is ClubSet.PROMOTED and code not in promoted:
        return False
    if rule.positions is not None and player.position not in rule.positions:
        return False
    if rule.nationalities is not None and player.nationality not in rule.nationalities:
        return False
    if rule.min_age is not None and (player.age is None or player.age < rule.min_age):
        return False
    if rule.max_age is not None and (player.age is None or player.age > rule.max_age):
        return False
    if player.minutes < rule.min_minutes:
        return False
    if rule.min_minutes_share > 0:
        club_minutes = club_matches.get(code, 0) * 90
        if club_minutes == 0 or player.minutes < rule.min_minutes_share * club_minutes:
            return False
    if player.rated_appearances < rule.min_rated_appearances:
        return False
    return True


def score(metric: Metric, player: PlayerFacts) -> tuple[float, ...] | None:
    """A player's ranking key, higher first, or None when the metric does not apply."""
    valuation = player.valuation or 0.0
    if metric is Metric.VALUATION:
        return None if player.valuation is None else (player.valuation,)
    if metric is Metric.NON_PENALTY_GOALS:
        if player.non_penalty_goals <= 0:
            return None
        # Ties go to the player who needed fewer minutes.
        return (float(player.non_penalty_goals), -float(player.minutes))
    if metric is Metric.CREATIVITY:
        if player.minutes <= 0:
            return None
        chances = player.chances_created
        return (chances * 90 / player.minutes, valuation) if chances > 0 else None
    if metric is Metric.RECENT_RATING:
        if player.recent_rating is None:
            return None
        return (player.recent_rating, float(player.rated_appearances))
    if metric is Metric.GOALSCORER_ODDS:
        if player.goalscorer_probability is None:
            return None
        return (player.goalscorer_probability, valuation)
    if metric is Metric.SOCIAL_BUZZ:
        if not player.social_mentions:
            return None
        sentiment = player.social_sentiment or 0.0
        buzz = player.social_mentions * (1 + max(-1.0, min(1.0, sentiment)))
        return (buzz, float(player.social_mentions)) if buzz > 0 else None
    if metric is Metric.KEEPER_MINUTES:
        return (float(player.keeper_minutes), valuation)
    if metric is Metric.MINUTES:
        return (float(player.minutes), valuation)
    raise ValueError(f"unknown metric {metric}")


def select_members(
    definition: RuleFundDefinition,
    league: LeagueFacts,
    current: frozenset[UUID] = frozenset(),
) -> tuple[UUID, ...]:
    """The rule's members, given the fund's current members for the buffer."""
    club_matches = league.club_matches()
    promoted = league.promoted_clubs()
    eligible = [
        player
        for player in league.players
        if is_eligible(definition, player, league, club_matches=club_matches, promoted=promoted)
    ]
    if definition.rank_by is None:
        return tuple(sorted(player.instrument_id for player in eligible))

    scored = [
        (key, player) for player in eligible
        if (key := score(definition.rank_by, player)) is not None
    ]
    # Best first; a current member wins a tie, then instrument id keeps the order stable.
    scored.sort(key=lambda item: (
        tuple(-value for value in item[0]),
        item[1].instrument_id not in current,
        str(item[1].instrument_id),
    ))
    ranked = [player.instrument_id for _, player in scored]

    if definition.one_per_club:
        best: dict[str, UUID] = {}
        for _, player in scored:
            best.setdefault(club_code(player.club), player.instrument_id)
        return tuple(sorted(best.values()))

    size = definition.size or len(ranked)
    return tuple(sorted(_buffered_window(
        ranked, current, start=definition.rank_from, size=size, buffer=definition.buffer
    )))


def _buffered_window(
    ranked: list[UUID], current: frozenset[UUID], *, start: int, size: int, buffer: int
) -> list[UUID]:
    """Ranks `start` to `start + size - 1`, holding current members within `buffer` places
    outside that window and taking newcomers only once they are `buffer` places inside it."""
    rank = {instrument_id: position for position, instrument_id in enumerate(ranked, start=1)}
    low, high = start, start + size - 1

    def distance(instrument_id: UUID) -> int:
        position = rank[instrument_id]
        return low - position if position < low else max(0, position - high)

    if buffer <= 0 or not current:
        return [i for i in ranked if low <= rank[i] <= high]
    kept = {i for i in current if i in rank and distance(i) <= buffer}
    # A window from the top has no upper cut-off to clear.
    entry_low = low + buffer if low > 1 else 1
    entering = {i for i in ranked if entry_low <= rank[i] <= high - buffer}
    selected = kept | entering
    order = sorted(selected, key=lambda i: (distance(i), rank[i]))
    if len(order) > size:
        return order[:size]
    rest = sorted(
        (i for i in ranked if i not in selected), key=lambda i: (distance(i), rank[i])
    )
    return order + rest[: size - len(order)]


def launch_basket(
    definition: RuleFundDefinition, members: tuple[UUID, ...], prices: dict[UUID, Decimal]
) -> tuple[tuple[UUID, str], ...]:
    """Shares per unit for a new fund, so a unit lists at `LAUNCH_UNIT_PRICE`."""
    if definition.weighting is Weighting.EQUAL_VALUE:
        per_member = LAUNCH_UNIT_PRICE / len(members)
        return tuple(
            (member, _shares(per_member / prices[member])) for member in members
        )
    shares = _shares(LAUNCH_UNIT_PRICE / sum(prices[member] for member in members))
    return tuple((member, shares) for member in members)


def _shares(value: Decimal) -> str:
    return str(max(SHARES_QUANTUM, value.quantize(SHARES_QUANTUM, rounding=ROUND_DOWN)))


def value_drift(holdings: dict[UUID, tuple[Decimal, Decimal]]) -> float:
    """How far the most out-of-line member's value is from an equal share, relative to it."""
    values = {member: shares * price for member, (shares, price) in holdings.items()}
    total = sum(values.values())
    if not values or total <= 0:
        return 0.0
    equal = total / len(values)
    return float(max(abs(value - equal) for value in values.values()) / equal)


def definition_for(key: str) -> RuleFundDefinition | None:
    return next((d for d in RULE_FUNDS if d.key == key), None)
