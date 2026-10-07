from __future__ import annotations

import unittest
from random import Random

from app.player_stats import (
    RATING_PRIOR_NINETIES,
    RatingTotals,
    build_rating_profile,
    build_rating_profiles,
    league_median_rating,
    rating_prior,
)
from app.synthetic_traders.models import StrategyEngine
from app.synthetic_traders.randomization import build_random_config_overrides


def _totals(rating: float, nineties: float, *, recent: tuple[float, float] | None = None):
    recent_rating, recent_nineties = recent or (rating, nineties)
    return RatingTotals(
        weighted_sum=rating * nineties,
        nineties=nineties,
        recent_weighted_sum=recent_rating * recent_nineties,
        recent_nineties=recent_nineties,
    )


class RatingProfileTests(unittest.TestCase):
    def test_two_great_games_lean_on_the_prior(self) -> None:
        profile = build_rating_profile(2026, _totals(8.5, 2.0), prior=7.0)
        expected = (8.5 * 2 + 7.0 * RATING_PRIOR_NINETIES) / (2 + RATING_PRIOR_NINETIES)
        self.assertAlmostEqual(profile.rating, expected)
        self.assertAlmostEqual(profile.prior_weight, 0.8)

    def test_a_full_season_outweighs_the_prior(self) -> None:
        profile = build_rating_profile(2026, _totals(7.4, 30.0), prior=6.95)
        self.assertGreater(profile.rating, 7.3)

    def test_prior_is_last_season_steadied_toward_the_league(self) -> None:
        prior = rating_prior(_totals(7.4, 20.0), league=6.95)
        self.assertAlmostEqual(prior, (7.4 * 20 + 6.95 * 8) / 28)

    def test_a_short_last_season_falls_back_to_the_league(self) -> None:
        self.assertEqual(rating_prior(_totals(8.0, 3.0), league=6.95), 6.95)
        self.assertEqual(rating_prior(None, league=6.95), 6.95)

    def test_form_needs_earlier_football_to_compare_with(self) -> None:
        only_recent = build_rating_profile(2026, _totals(7.0, 4.0), prior=6.95)
        self.assertIsNone(only_recent.form)
        season = RatingTotals(
            weighted_sum=7.5 * 4 + 6.8 * 6,
            nineties=10.0,
            recent_weighted_sum=7.5 * 4,
            recent_nineties=4.0,
        )
        profile = build_rating_profile(2026, season, prior=6.95)
        self.assertIsNotNone(profile.form)
        self.assertAlmostEqual(profile.form or 0.0, 7.5 - season.weighted_sum / 10.0)

    def test_without_removes_one_appearance(self) -> None:
        before = _totals(7.0, 9.0).without(9.0, 1.0)
        self.assertAlmostEqual(before.nineties, 8.0)
        self.assertAlmostEqual(before.mean or 0.0, (63.0 - 9.0) / 8.0)
        self.assertEqual(_totals(9.0, 1.0).without(9.0, 1.0).nineties, 0.0)

    def test_league_median_ignores_bit_part_players(self) -> None:
        median = league_median_rating(
            [_totals(6.8, 20.0), _totals(7.0, 20.0), _totals(7.2, 20.0), _totals(9.9, 1.0)]
        )
        self.assertAlmostEqual(median or 0.0, 7.0)

    def test_profiles_need_a_league_to_steady_against(self) -> None:
        self.assertEqual(build_rating_profiles(2026, {"p": _totals(7.0, 2.0)}, {}), {})
        profiles = build_rating_profiles(
            2026, {"p": _totals(7.5, 2.0)}, {"q": _totals(7.0, 20.0), "p": _totals(7.2, 30.0)}
        )
        self.assertEqual(set(profiles), {"p", "q"})
        self.assertEqual(profiles["q"].rated_nineties, 0.0)


class StyleSamplingTests(unittest.TestCase):
    def test_a_form_chasing_profile_keeps_mostly_chasing_form(self) -> None:
        base = {
            "stats_inputs": {
                "rating_weight": 0.2,
                "goals_weight": 0.12,
                "assists_weight": 0.08,
                "clean_sheet_weight": 0.04,
                "defensive_actions_weight": 0.06,
                "shots_weight": 0.05,
                "key_passes_weight": 0.04,
                "minutes_weight": 0.08,
                "form_weight": 0.7,
            }
        }
        random_source = Random(7)
        form_shares = []
        for _ in range(200):
            inputs = build_random_config_overrides(
                config_key="STATS_VALUE_FORM_CHASER",
                strategy_engine=StrategyEngine.STATS_VALUE,
                base_config=base,
                random_source=random_source,
            )["stats_inputs"]
            total = sum(value for key, value in inputs.items() if key != "rating_weight")
            form_shares.append(inputs["form_weight"] / total)
        # The profile puts 0.7 of 1.17 (60%) on form; an uncentred draw would average 20%.
        self.assertGreater(sum(form_shares) / len(form_shares), 0.45)


if __name__ == "__main__":
    unittest.main()
