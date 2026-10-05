from __future__ import annotations

import unittest
from random import Random

from app.player_stats import SeasonTotals, build_profile, per90_rates
from app.player_stats.profiles import PRIOR_STRENGTH_NINETIES
from app.synthetic_traders.models import StrategyEngine
from app.synthetic_traders.randomization import STATS_STYLE_GROUPS, build_random_config_overrides


def _tables(*, minutes=900, games=10, goals=3, assists=2, shots=20, tackles_won=15,
            interceptions=10, defense_90s=10.0, team="Everton"):
    return {
        "standard": [{"games": games, "games_starts": games, "minutes": minutes, "goals": goals,
                      "assists": assists, "cards_yellow": 1, "cards_red": 0, "team": team}],
        "shooting": [{"shots": shots, "goals": goals}],
        "passing": [{"assisted_shots": None, "assists": assists}],
        "defense": [{"tackles_won": tackles_won, "interceptions": interceptions, "blocks": None,
                     "minutes_90s": defense_90s}],
    }


class SeasonTotalsTests(unittest.TestCase):
    def test_reads_each_stat_from_its_own_table_not_every_table(self) -> None:
        totals = SeasonTotals.from_tables(_tables())
        # Goals appear in the standard and shooting tables; they must count once.
        self.assertEqual(totals.goals, 3)
        self.assertEqual(totals.assists, 2)
        self.assertEqual(totals.minutes, 900)
        self.assertEqual(totals.defensive_actions, 25)
        rates = per90_rates(totals)
        self.assertAlmostEqual(rates["goals"], 0.3)
        self.assertAlmostEqual(rates["defensive_actions"], 2.5)

    def test_a_mid_season_transfer_adds_both_clubs(self) -> None:
        first, second = _tables(team="Everton"), _tables(minutes=450, games=5, goals=1, team="Spurs")
        combined = {name: first[name] + second[name] for name in first}
        totals = SeasonTotals.from_tables(combined)
        self.assertEqual(totals.goals, 4)
        self.assertEqual(totals.minutes, 1350)

    def test_missing_values_count_as_nothing(self) -> None:
        totals = SeasonTotals.from_tables(_tables())
        self.assertEqual(totals.key_passes, 0)


class ProfileTests(unittest.TestCase):
    def test_early_season_rates_lean_on_the_prior(self) -> None:
        # Two full games with two goals: 1.0 per 90 on its own, far above a 0.2 prior.
        early = SeasonTotals.from_tables(_tables(minutes=180, games=2, goals=2))
        profile = build_profile(2026, early, {"goals": 0.2})
        expected = (2 + 0.2 * PRIOR_STRENGTH_NINETIES) / (2 + PRIOR_STRENGTH_NINETIES)
        self.assertAlmostEqual(profile.goals_per90, expected)
        self.assertGreater(profile.prior_weight, 0.75)

    def test_form_is_measured_over_the_minutes_since_the_base_snapshot(self) -> None:
        base = SeasonTotals.from_tables(_tables(minutes=900, games=10, goals=1, assists=0))
        latest = SeasonTotals.from_tables(_tables(minutes=1170, games=13, goals=4, assists=1))
        profile = build_profile(2026, latest, {}, form_base=base)
        self.assertAlmostEqual(profile.recent_minutes, 270)
        self.assertAlmostEqual(profile.recent_goal_involvements_per90, 4 / 3)

    def test_too_little_recent_football_gives_no_form(self) -> None:
        base = SeasonTotals.from_tables(_tables(minutes=900))
        latest = SeasonTotals.from_tables(_tables(minutes=960))
        self.assertIsNone(build_profile(2026, latest, {}, form_base=base).recent_goal_involvements_per90)


class StatsStyleTests(unittest.TestCase):
    BASE = {"stats_inputs": {"goals_weight": 0.3, "assists_weight": 0.2, "shots_weight": 0.1,
                             "key_passes_weight": 0.1, "defensive_actions_weight": 0.1,
                             "clean_sheet_weight": 0.05, "rating_weight": 0.2,
                             "cards_penalty_weight": -0.05}}

    def _style(self, seed: int) -> dict[str, float]:
        overrides = build_random_config_overrides(
            config_key="STATS_VALUE_AGGRESSIVE",
            strategy_engine=StrategyEngine.STATS_VALUE,
            base_config=self.BASE,
            random_source=Random(seed),
        )
        return overrides["stats_inputs"]

    def test_styles_keep_the_profiles_total_weight(self) -> None:
        weights = self._style(1)
        style_keys = [key for group in STATS_STYLE_GROUPS.values() for key in group]
        expected_total = 0.3 + 0.2 + 0.1 + 0.1 + 0.1 + 0.05 + 0.15 + 0.1
        self.assertAlmostEqual(sum(weights[key] for key in style_keys), expected_total, places=4)

    def test_bots_draw_genuinely_different_priorities(self) -> None:
        def favourite(weights):
            groups = {
                name: sum(weights[key] for key in split)
                for name, split in STATS_STYLE_GROUPS.items()
            }
            return max(groups, key=lambda name: groups[name])

        favourites = {favourite(self._style(seed)) for seed in range(40)}
        # Forty bots don't all care most about the same thing.
        self.assertGreaterEqual(len(favourites), 4)


if __name__ == "__main__":
    unittest.main()
