from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import CurrentPrincipal
from app.blind_market.replays import CANDIDATES, build_replay
from app.clients.trading_engine import HttpTradingEngineClient
from app.database import connection

DUBLIN = ZoneInfo("Europe/Dublin")
PAYOUT_PERCENT = (0, 0, 5, 15, 35, 60, 100)
CASH_PRECISION = Decimal("0.0001")


class Guess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["up", "down"]
    band: Literal["small", "medium", "large"]


class Call(BaseModel):
    """One player's call. Each card is called, scored and revealed on its own."""

    model_config = ConfigDict(extra="forbid")

    day: date
    slot: int = Field(ge=0, le=2)
    guess: Guess


class RoundClosedError(Exception):
    pass


def score_guess(guess: Guess, move: Decimal) -> int:
    direction = "up" if move > 0 else "down"
    if guess.direction != direction:
        return 0
    magnitude = abs(move)
    band = "small" if magnitude < 2 else "medium" if magnitude < 5 else "large"
    return 2 if guess.band == band else 1


def progress(guesses: list[dict[str, Any] | None], answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Points for each player called so far, and the round's score once all three are called.

    An entry keeps one guess per player, null until that player is called.
    """
    points = [
        score_guess(Guess.model_validate(guess), Decimal(answer["move"])) if guess else None
        for guess, answer in zip(guesses, answers, strict=True)
    ]
    called = [point for point in points if point is not None]
    return {"points": points, "score": sum(called) if len(called) == len(points) else None}


# An entry is complete once no player is left uncalled.
COMPLETE = "NOT entry.guesses @> '[null]'::jsonb"


def reward_for_score(weekly_topup: Decimal, score: int) -> Decimal:
    return (weekly_topup * PAYOUT_PERCENT[score] / 100).quantize(CASH_PRECISION, ROUND_HALF_UP)


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, DUBLIN).astimezone(UTC)


def _lock(cursor: RealDictCursor, key: str) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def _find_round(cursor: RealDictCursor, day: date) -> dict[str, Any] | None:
    cursor.execute("SELECT * FROM blind_market_rounds WHERE day = %s", (day,))
    return cursor.fetchone()


class BlindMarketService:
    def __init__(
        self, database_url: str, engine: HttpTradingEngineClient, weekly_topup: Decimal
    ) -> None:
        if (
            not weekly_topup.is_finite()
            or not Decimal("0.0001") <= weekly_topup < Decimal("10000000000000000")
            or weekly_topup != weekly_topup.quantize(CASH_PRECISION)
        ):
            raise ValueError("Daily Games weekly top-up must be positive with at most four decimals")
        self.database_url = database_url
        self.engine = engine
        self.weekly_topup = weekly_topup

    def _create_round(self, cursor: RealDictCursor, day: date) -> dict[str, Any] | None:
        week = day - timedelta(days=day.weekday())
        # A week has one prize pot even if the configured amount changes midweek.
        _lock(cursor, f"blind-market:week:{week}")
        existing = _find_round(cursor, day)
        if existing:
            return existing
        cursor.execute(CANDIDATES, {"anchor": _local_midnight(day) - timedelta(days=2), "day": day})
        players = cursor.fetchall()
        if len(players) < 3:
            return None
        cards, answers = zip(*(build_replay(cursor, player) for player in players))
        cursor.execute(
            """
            INSERT INTO blind_market_rounds (day, week_start, closes_at, weekly_topup, cards, answers)
            VALUES (%s, %s, %s, coalesce(
                (SELECT weekly_topup FROM blind_market_rounds WHERE week_start = %s
                 ORDER BY day LIMIT 1), %s), %s, %s)
            RETURNING *
            """,
            (day, week, _local_midnight(day + timedelta(days=1)), week,
             self.weekly_topup, Json(cards), Json(answers)),
        )
        return cursor.fetchone()

    def round_view(self, day: date | None, account_id: UUID | None) -> dict[str, Any]:
        now = datetime.now(UTC)
        today = now.astimezone(DUBLIN).date()
        selected = day or today
        with connection(self.database_url) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            round_ = _find_round(cur, selected) if selected <= today else None
            if round_ is None and selected == today:
                round_ = self._create_round(cur, selected)
            pending = Decimal(0)
            entry = None
            if account_id:
                cur.execute(
                    f"""
                    SELECT coalesce(sum(entry.reward), 0) AS amount
                    FROM blind_market_entries entry
                    WHERE entry.account_id = %s AND entry.claimed_at IS NULL AND {COMPLETE}
                    """,
                    (str(account_id),),
                )
                totals = cur.fetchone()
                assert totals is not None
                pending = totals["amount"]
                if round_:
                    cur.execute(
                        """
                        SELECT guesses, score, reward FROM blind_market_entries
                        WHERE account_id = %s AND day = %s
                        """,
                        (str(account_id), selected),
                    )
                    entry = cur.fetchone()

        closed = bool(round_ and round_["closes_at"] <= now)
        answers = round_["answers"] if round_ else []
        # A closed round reveals everyone; an open one only the players this account has called.
        results: list[Any] | None = None
        if closed:
            results = answers
        elif entry:
            results = [
                answer if guess else None
                for guess, answer in zip(entry["guesses"], answers, strict=True)
            ]
        view = {
            "day": selected,
            "today": today,
            "closes_at": round_["closes_at"] if round_ else None,
            "state": "closed" if closed else "open" if round_ else "unavailable",
            "cards": round_["cards"] if round_ else [],
            "weekly_topup": str(round_["weekly_topup"] if round_ else self.weekly_topup),
            "payout_percent": PAYOUT_PERCENT,
            "pending_reward": str(pending),
            "entry": None,
            "results": results,
        }
        if round_ and entry:
            scored = progress(entry["guesses"], answers)
            view["entry"] = {
                "guesses": entry["guesses"],
                "points": scored["points"],
                "score": scored["score"],
                "reward": str(entry["reward"]) if scored["score"] is not None else None,
            }
        return view

    def call(self, account_id: UUID, call: Call) -> dict[str, Any]:
        """Records one player's call and reveals that player.

        Calling a player twice keeps the first call.
        """
        with connection(self.database_url) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            _lock(cur, f"blind-market:account:{account_id}")
            round_ = _find_round(cur, call.day)
            if not round_ or round_["closes_at"] <= datetime.now(UTC):
                raise RoundClosedError
            cur.execute(
                """
                SELECT guesses, reward FROM blind_market_entries
                WHERE account_id = %s AND day = %s
                """,
                (str(account_id), call.day),
            )
            existing = cur.fetchone()
            guesses: list[dict[str, Any] | None] = (
                list(existing["guesses"]) if existing else [None] * len(round_["answers"])
            )
            reward = existing["reward"] if existing else Decimal(0)
            if guesses[call.slot] is None:
                guesses[call.slot] = call.guess.model_dump()
                scored = progress(guesses, round_["answers"])
                running = sum(point for point in scored["points"] if point is not None)
                if scored["score"] is not None:
                    cur.execute(
                        f"""
                        SELECT coalesce(max(entry.score), 0) AS best
                        FROM blind_market_entries entry JOIN blind_market_rounds round USING (day)
                        WHERE entry.account_id = %s AND round.week_start = %s
                          AND entry.day <> %s AND {COMPLETE}
                        """,
                        (str(account_id), round_["week_start"], call.day),
                    )
                    totals = cur.fetchone()
                    assert totals is not None
                    pot = round_["weekly_topup"]
                    reward = max(
                        Decimal(0),
                        reward_for_score(pot, running) - reward_for_score(pot, totals["best"]),
                    )
                cur.execute(
                    """
                    INSERT INTO blind_market_entries (account_id, day, guesses, score, reward)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (account_id, day) DO UPDATE
                    SET guesses = EXCLUDED.guesses, score = EXCLUDED.score, reward = EXCLUDED.reward
                    """,
                    (str(account_id), call.day, Json(guesses), running, reward),
                )
            scored = progress(guesses, round_["answers"])
        return {
            "slot": call.slot,
            "guesses": guesses,
            "points": scored["points"],
            "result": round_["answers"][call.slot],
            "score": scored["score"],
            "reward": str(reward) if scored["score"] is not None else None,
        }

    def claim(self, principal: CurrentPrincipal) -> None:
        with connection(self.database_url) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT entry.day, entry.reward
                FROM blind_market_entries entry
                WHERE entry.account_id = %s AND entry.claimed_at IS NULL AND entry.reward > 0
                  AND {COMPLETE}
                ORDER BY entry.day LIMIT 10
                """,
                (str(principal.account_id),),
            )
            rewards = cur.fetchall()
        for reward in rewards:
            # The immutable account/day key makes a timeout or concurrent claim safe to retry.
            self.engine.apply_blind_market_reward(
                account_id=principal.account_id, portfolio_id=principal.portfolio_id,
                amount=reward["reward"], day=reward["day"].isoformat(),
            )
            with connection(self.database_url) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE blind_market_entries SET claimed_at = now()
                    WHERE account_id = %s AND day = %s AND claimed_at IS NULL
                    """,
                    (str(principal.account_id), reward["day"]),
                )
