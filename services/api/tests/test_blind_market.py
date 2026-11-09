from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.blind_market.replays import recent_form
from app.blind_market.service import Call, Guess, progress, reward_for_score, score_guess


@pytest.mark.parametrize(
    ("move", "direction", "band", "points"),
    [
        ("1.999999", "up", "small", 2),
        ("2.000000", "up", "small", 1),
        ("2.000000", "up", "medium", 2),
        ("-4.999999", "down", "medium", 2),
        ("-5.000000", "down", "large", 2),
        ("-5.000000", "up", "large", 0),
    ],
)
def test_direction_and_band_boundaries(move, direction, band, points):
    assert score_guess(Guess(direction=direction, band=band), Decimal(move)) == points


def test_weekly_topup_for_a_perfect_round_and_smaller_awards():
    topup = Decimal("100000")
    awards = [reward_for_score(topup, score) for score in range(7)]
    assert awards == [0, 0, 5000, 15000, 35000, 60000, topup]
    assert awards[4] + (awards[6] - awards[4]) == topup


def _appearance(index: int, chances: int, minutes: int = 90) -> dict:
    return {
        "season": 2026,
        "kickoff_at": datetime(2026, 10, 20, tzinfo=UTC) - timedelta(days=index),
        "opponent": f"Club {index}",
        "minutes_played": minutes,
        "rating": Decimal("7.34"),
        "raw_payload": {
            "stats": [{"stats": {
                "Chances created": {"key": "chances_created", "stat": {"value": chances}},
                "Tackles": {"key": "matchstats.headers.tackles", "stat": {"value": 1}},
                "Interceptions": {"key": "interceptions", "stat": {"value": 2}},
            }}]
        },
    }


def test_anonymous_form_uses_five_recent_appearances_and_older_season_baseline():
    matches = [_appearance(i, 3 if i < 5 else 1) for i in range(10)]
    clue, reveal = recent_form(matches, "Midfielder")
    assert clue["appearances"] == 5
    assert clue["rating"] == 7.5
    assert clue["metrics"] == [
        {"label": "Chances created", "value": 3, "unit": "/ 90", "comparison": "Above usual"},
        {"label": "Tackles + interceptions", "value": 3, "unit": "/ 90", "comparison": "Typical"},
    ]
    assert "matches" not in clue
    assert len(reveal["matches"]) == 5
    assert reveal["matches"][0]["opponent"] == "Club 0"
    assert reveal["rating"] == 7.34


def test_low_minutes_do_not_produce_a_before_guess_rate():
    clue, reveal = recent_form([_appearance(0, 2, minutes=28)], "Midfielder")
    assert clue["limited_minutes"]
    assert not clue["metrics"]
    assert reveal["minutes"] == 28


ANSWERS = [{"move": "3.1"}, {"move": "-0.4"}, {"move": "6.0"}]


def test_each_called_player_is_scored_before_the_round_is_complete():
    guesses = [{"direction": "up", "band": "medium"}, None, None]
    assert progress(guesses, ANSWERS) == {"points": [2, None, None], "score": None}


def test_the_round_scores_once_every_player_is_called():
    guesses = [
        {"direction": "up", "band": "medium"},
        {"direction": "up", "band": "small"},
        {"direction": "up", "band": "medium"},
    ]
    assert progress(guesses, ANSWERS) == {"points": [2, 0, 1], "score": 3}


@pytest.mark.parametrize("slot", [-1, 3])
def test_a_call_names_one_of_the_three_players(slot):
    with pytest.raises(ValueError):
        Call.model_validate(
            {"day": "2026-11-07", "slot": slot, "guess": {"direction": "up", "band": "small"}}
        )
