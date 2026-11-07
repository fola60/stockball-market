from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg2.extras import RealDictCursor

DAY = timedelta(days=1)

# Each eligible window contains real executions and a material price move. The first
# execution's old price is the standing quote at the start of the 24-hour window.
CANDIDATES = """
    WITH snapshots AS (
        SELECT s.*, date_bin('24 hours', s.captured_at, %(anchor)s) AS cutoff
        FROM price_snapshots s
        WHERE s.captured_at >= %(anchor)s - interval '504 hours'
          AND s.captured_at < %(anchor)s
    ),
    windows AS (
        SELECT instrument_id, cutoff,
               (array_agg(old_price ORDER BY captured_at, id))[1] AS opening,
               (array_agg(new_price ORDER BY captured_at DESC, id DESC))[1] AS closing
        FROM snapshots
        GROUP BY instrument_id, cutoff
        HAVING count(*) >= 2 AND bool_and(reason IN ('TRADE_BUY', 'TRADE_SELL'))
    ),
    eligible AS (
        SELECT w.*, p.id AS player_id, p.display_name, p.position,
               (closing - opening) * 100 / nullif(opening, 0) AS move
        FROM windows w
        JOIN instruments i ON i.id = w.instrument_id AND i.instrument_type = 'PLAYER_SHARE'
        JOIN players p ON p.id = i.player_id
        WHERE w.opening > 0 AND w.closing > 0
          AND abs(w.closing - w.opening) >= w.opening * 0.0025
          AND i.created_at <= w.cutoff - interval '168 hours'
          AND EXISTS (
              SELECT 1 FROM player_match_ratings r
              WHERE r.player_id = p.id AND r.minutes_played > 0
                AND r.updated_at <= w.cutoff
          )
          AND NOT EXISTS (
              SELECT 1
              FROM blind_market_rounds prior
              CROSS JOIN LATERAL jsonb_array_elements(prior.answers) AS answer(value)
              WHERE prior.day >= %(day)s - 24 AND prior.day < %(day)s
                AND answer.value->>'instrument_id' = i.id::text
                AND (answer.value->>'cutoff')::timestamptz = w.cutoff
          )
    )
    SELECT * FROM (
        SELECT DISTINCT ON (instrument_id) * FROM eligible ORDER BY instrument_id, random()
    ) AS distinct_players ORDER BY random() LIMIT 3
"""

ROLE_STATS = {
    "Forward": {
        "Goals + assists": (("goals",), ("assists",)),
        "Shots on target": (("ShotsOnTarget", "shots_on_target", "ontarget_scoring_att"),),
    },
    "Midfielder": {
        "Chances created": (("chances_created", "key_passes", "total_att_assist"),),
        "Tackles + interceptions": (("matchstats.headers.tackles", "tackles"), ("interceptions",)),
    },
    "Defender": {
        "Tackles + interceptions": (("matchstats.headers.tackles", "tackles"), ("interceptions",)),
        "Blocks": (("shot_blocks", "blocks", "outfielder_block"),),
    },
    "Goalkeeper": {
        "Saves": (("saves", "keeper_saves", "keeper_save"),),
        "Goals conceded": (("goals_conceded", "goals_conceded_by_player"),),
    },
}


def position_label(position: str | None) -> str:
    first = (position or "").split(",")[0].strip().upper()
    return {
        "GK": "Goalkeeper", "DF": "Defender", "DEF": "Defender",
        "MF": "Midfielder", "MID": "Midfielder", "FW": "Forward", "FWD": "Forward",
    }.get(first, "Player")


def _stat_values(payload: dict[str, Any]) -> dict[str, Decimal]:
    values = {}
    for group in payload.get("stats", []):
        for stat in group.get("stats", {}).values():
            value = stat.get("stat", {}).get("value")
            key = stat.get("key")
            if not key or value is None:
                continue
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                continue
            if number.is_finite() and number >= 0:
                values[key] = number
    return values


def _match_stats(match: dict[str, Any], role: str) -> dict[str, Decimal]:
    values = _stat_values(match["raw_payload"])
    result = {}
    for label, components in ROLE_STATS.get(role, {}).items():
        parts = [next((values[key] for key in keys if key in values), None) for keys in components]
        if any(part is not None for part in parts):
            result[label] = sum((part for part in parts if part is not None), Decimal(0))
    return result


def _rates(
    matches: Sequence[dict[str, Any]], role: str
) -> tuple[int, dict[str, Decimal], Decimal | None]:
    minutes = sum(match["minutes_played"] for match in matches)
    totals: dict[str, Decimal] = {}
    for match in matches:
        for label, value in _match_stats(match, role).items():
            totals[label] = totals.get(label, Decimal(0)) + value
    rates = {label: value * 90 / minutes for label, value in totals.items()} if minutes else {}
    if role == "Goalkeeper":
        saves = totals.get("Saves", Decimal(0))
        faced = saves + totals.get("Goals conceded", Decimal(0))
        rates.pop("Goals conceded", None)
        if faced > 0 and "Goals conceded" in totals:
            rates["Save percentage"] = saves * 100 / faced
    rated: list[Decimal] = [match["rating"] for match in matches if match["rating"] is not None]
    return minutes, rates, sum(rated, Decimal(0)) / len(rated) if rated else None


def recent_form(
    matches: Sequence[dict[str, Any]], role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    recent = matches[:5]
    baseline = [match for match in matches[5:] if match["season"] == recent[0]["season"]]
    minutes, rates, rating = _rates(recent, role)
    prior_minutes, prior_rates, _ = _rates(baseline, role)
    metrics = []
    for label, rate in rates.items():
        prior = prior_rates.get(label)
        comparison = None
        percentage = label == "Save percentage"
        if minutes >= 180 and prior_minutes >= 270 and prior is not None:
            margin = Decimal(5) if percentage else max(Decimal("0.25"), prior * Decimal("0.2"))
            comparison = "Above usual" if rate > prior + margin else (
                "Below usual" if rate < prior - margin else "Typical"
            )
        metrics.append({
            "label": label,
            "value": float(round(rate / 5) * 5 if percentage else round(rate * 2) / 2),
            "unit": "%" if percentage else "/ 90",
            "comparison": comparison,
        })

    return (
        {
            "appearances": len(recent),
            "minutes_low": minutes // 50 * 50,
            "limited_minutes": minutes < 180,
            "rating": float(round(rating * 2) / 2) if rating is not None else None,
            "metrics": metrics if minutes >= 180 else [],
        },
        {
            "minutes": minutes,
            "rating": float(round(rating, 2)) if rating is not None else None,
            "metrics": [
                {"label": label, "value": float(round(rate, 2)),
                 "unit": "%" if label == "Save percentage" else "/ 90"}
                for label, rate in rates.items()
            ],
            "matches": [
                {
                    "kickoff": match["kickoff_at"].isoformat(),
                    "opponent": match["opponent"],
                    "minutes": match["minutes_played"],
                    "rating": float(match["rating"]) if match["rating"] is not None else None,
                    "stats": {label: float(value) for label, value in _match_stats(match, role).items()},
                }
                for match in recent
            ],
        },
    )


def _chart(
    cursor: RealDictCursor, instrument_id: str, times: list[datetime]
) -> list[Decimal | None]:
    cursor.execute(
        """
        SELECT (
            SELECT new_price FROM price_snapshots
            WHERE instrument_id = %s AND captured_at < at
            ORDER BY captured_at DESC, id DESC LIMIT 1
        ) AS price
        FROM unnest(%s::timestamptz[]) WITH ORDINALITY AS sample(at, n)
        ORDER BY n
        """,
        (instrument_id, times),
    )
    return [row["price"] for row in cursor.fetchall()]


def _trade_volume(
    cursor: RealDictCursor, instrument_id: str, cutoff: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    cursor.execute(
        """
        SELECT coalesce(sum(shares) FILTER (
                   WHERE executed_at >= %(cutoff)s - interval '24 hours'
                     AND executed_at < %(cutoff)s AND side = 'BUY'), 0) AS buys,
               coalesce(sum(shares) FILTER (
                   WHERE executed_at >= %(cutoff)s - interval '24 hours'
                     AND executed_at < %(cutoff)s), 0) AS volume,
               coalesce(sum(shares) FILTER (
                   WHERE executed_at < %(cutoff)s - interval '24 hours'), 0) / 6 AS usual,
               coalesce(sum(shares) FILTER (
                   WHERE executed_at >= %(cutoff)s AND side = 'BUY'), 0) AS replay_buys,
               coalesce(sum(shares) FILTER (
                   WHERE executed_at >= %(cutoff)s AND side = 'SELL'), 0) AS replay_sells,
               count(*) FILTER (WHERE executed_at >= %(cutoff)s) AS replay_trades
        FROM trades
        WHERE instrument_id = %(id)s AND executed_at >= %(cutoff)s - interval '168 hours'
          AND executed_at < %(cutoff)s + interval '24 hours'
        """,
        {"id": instrument_id, "cutoff": cutoff},
    )
    trade = cursor.fetchone()
    assert trade is not None  # The aggregate always returns one row.
    volume, usual = trade["volume"], trade["usual"]
    share = min(90, int(trade["buys"] * 10 / volume) * 10) if volume else None
    activity = "No trades" if not volume else (
        "High" if volume > usual * Decimal("1.5")
        else "Low" if volume < usual * Decimal("0.5") else "Typical"
    )
    return (
        {"buy_share_low": share, "activity": activity},
        {"buys": str(trade["replay_buys"]), "sells": str(trade["replay_sells"]),
         "trades": trade["replay_trades"]},
    )


def _context(
    cursor: RealDictCursor, instrument_id: str, player_id: str, cutoff: datetime
) -> tuple[str | None, str | None]:
    cursor.execute(
        """
        SELECT CASE WHEN released_at IS NULL OR released_at > %(cutoff)s
                    THEN 'Trading paused for a match'
                    ELSE 'Trading recently reopened after a match' END AS match_status
        FROM instrument_freezes
        WHERE instrument_id = %(id)s AND reason = 'MATCH_DAY'
          AND started_at <= %(cutoff)s
          AND (released_at IS NULL OR released_at > %(cutoff)s - interval '12 hours')
        ORDER BY started_at DESC LIMIT 1
        """,
        {"id": instrument_id, "cutoff": cutoff},
    )
    freeze = cursor.fetchone()
    cursor.execute(
        """
        SELECT stage FROM player_injury_availability_observations
        WHERE player_id = %(player)s AND created_at <= %(cutoff)s AND observed_at <= %(cutoff)s
          AND observed_at > %(cutoff)s - interval '14 days' AND confidence >= 0.6
        ORDER BY observed_at DESC, created_at DESC LIMIT 1
        """,
        {"player": player_id, "cutoff": cutoff},
    )
    injury = cursor.fetchone()
    availability = {
        "SUSPECTED_INJURY": "Reported injury concern",
        "CONFIRMED_INJURY": "Reported injured",
        "SUSPECTED_RECOVERY": "Reported close to returning",
        "CONFIRMED_RECOVERED": "Recently cleared to play",
    }.get(injury["stage"]) if injury else None
    cursor.execute(
        """
        SELECT credibility_weighted_sentiment AS sentiment, trusted_mention_count AS mentions
        FROM player_social_signal_snapshots
        WHERE player_id = %s AND calculated_at <= %s
          AND calculated_at > %s - interval '48 hours' AND signal_confidence >= 0.6
          AND trusted_mention_count >= 2
        ORDER BY calculated_at DESC, lookback_seconds LIMIT 1
        """,
        (player_id, cutoff, cutoff),
    )
    signal = cursor.fetchone()
    attention = None
    if signal:
        sentiment = signal["sentiment"] or 0
        attention = "Recent coverage leaned positive" if sentiment >= 0.2 else (
            "Recent coverage leaned negative" if sentiment <= -0.2
            else "The player appeared in several trusted reports"
        )
    status = " · ".join(filter(None, [freeze["match_status"] if freeze else None, availability]))
    return status or None, attention


def build_replay(
    cursor: RealDictCursor, player: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    instrument_id = str(player["instrument_id"])
    cutoff = player["cutoff"]
    cursor.execute(
        """
        SELECT m.season, m.kickoff_at, r.team_name, r.minutes_played, r.rating, r.raw_payload,
               CASE WHEN r.team_provider_id = m.home_team_id
                    THEN m.away_team_name ELSE m.home_team_name END AS opponent
        FROM player_match_ratings r
        JOIN fotmob_matches m ON m.match_id = r.provider_match_id
        WHERE r.player_id = %s AND r.minutes_played > 0 AND m.kickoff_at < %s
          AND r.updated_at <= %s
        ORDER BY m.kickoff_at DESC, m.match_id
        LIMIT 45
        """,
        (str(player["player_id"]), cutoff, cutoff),
    )
    position = position_label(player["position"])
    matches = list(cursor.fetchall())
    form, full_form = recent_form(matches, position)
    trading, full_trading = _trade_volume(cursor, instrument_id, cutoff)
    match_status, attention = _context(cursor, instrument_id, str(player["player_id"]), cutoff)
    prior = _chart(cursor, instrument_id, [cutoff - DAY * n for n in range(7, 0, -1)])
    after = _chart(cursor, instrument_id, [cutoff + timedelta(hours=n) for n in range(4, 24, 4)])
    base = next((price for price in prior if price and price > 0), player["opening"])
    prices = [*prior, player["opening"]]
    return (
        {
            "position": position,
            "chart": [float(round(price * 200 / base) / 2) if price else None for price in prices],
            "form": form,
            "trading": trading,
            "match_status": match_status,
            "attention": attention,
        },
        {
            "instrument_id": instrument_id,
            "name": player["display_name"],
            "club": matches[0]["team_name"] if matches else None,
            "cutoff": cutoff.isoformat(),
            "move": str(player["move"]),
            "chart": [float(price * 100 / base) if price else None
                      for price in [*prices, *after, player["closing"]]],
            "opening": str(player["opening"]),
            "closing": str(player["closing"]),
            "trading": full_trading,
            "form": full_form,
        },
    )
