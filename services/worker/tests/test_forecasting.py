from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from random import Random
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.forecasting import (
    FEATURE_NAMES,
    Appearance,
    Fixture,
    ForecastService,
    HorizonResult,
    RidgeModel,
    StoredModel,
    build_rows,
    promotion_decision,
    train,
)
from app.forecasting import ridge as ridge_module
from app.forecasting.dataset import MatchHistory
from app.forecasting.training import MIN_TRAINING_ROWS
from app.jobs.fotmob import FotMobRatingsJobHandler
from app.jobs.models import JobType, WorkerJob
from app.synthetic_traders import (
    BotStatus,
    PlayerForecastContext,
    StrategyEngine,
    SyntheticTraderBotRecord,
    apply_config_overrides,
    parse_strategy_config,
)
from app.synthetic_traders.engines import ForecastValueStrategyEngine
from app.synthetic_traders.models import DecisionSide
from app.synthetic_traders.randomization import build_random_config_overrides
from tests.test_synthetic_trader_configs import _migration_profiles
from tests.test_synthetic_trader_engines import _candidate, _context

START = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
TEAMS = [f"team-{index}" for index in range(8)]


def _league(
    seasons: int = 2, players_per_team: int = 14, seed: int = 7, form_effect: float = 0.5
) -> tuple[list[Appearance], list[Fixture]]:
    """A small league in which a player's next ratings follow his true level plus a share of
    his last match's surprise, so recent form genuinely predicts what comes next."""
    random = Random(seed)
    levels = {
        (team, slot): 6.9 + random.gauss(0.0, 0.3)
        for team in TEAMS
        for slot in range(players_per_team)
    }
    carry = dict.fromkeys(levels, 0.0)
    appearances: list[Appearance] = []
    fixtures: list[Fixture] = []
    match_number = 0
    for season in range(seasons):
        for round_index in range(28):
            kickoff = START + timedelta(days=365 * season + 7 * round_index)
            order = TEAMS[round_index % len(TEAMS) :] + TEAMS[: round_index % len(TEAMS)]
            for home, away in zip(order[::2], order[1::2], strict=True):
                match_number += 1
                match_id = f"m{match_number}"
                fixtures.append(
                    Fixture(match_id, 2024 + season, kickoff, home, away, True, 1, 1, 0.1)
                )
                for team in (home, away):
                    for slot in range(players_per_team):
                        key = (team, slot)
                        surprise = random.gauss(0.0, 0.5)
                        rating = levels[key] + carry[key] + surprise
                        carry[key] = form_effect * (carry[key] + surprise)
                        appearances.append(
                            Appearance(
                                provider_player_id=f"{team}-{slot}",
                                player_id=str(UUID(int=TEAMS.index(team) * 100 + slot + 1)),
                                match_id=match_id,
                                season=2024 + season,
                                kickoff_at=kickoff,
                                team_id=team,
                                rating=rating,
                                minutes=90,
                                position=slot % 4,
                            )
                        )
    return appearances, fixtures


def test_ridge_recovers_a_linear_relationship_and_explains_it():
    random = Random(3)
    rows = [{"a": random.gauss(0, 1), "b": random.gauss(5, 2)} for _ in range(400)]
    targets = [2.0 * row["a"] - 0.5 * row["b"] + 1.0 for row in rows]
    model = ridge_module.prepare(("a", "b"), rows, targets, [1.0] * len(rows)).solve(1e-6)

    assert model.predict({"a": 1.0, "b": 4.0}) == pytest.approx(1.0, abs=1e-3)
    contributions = model.contributions({"a": 1.0, "b": None})
    # A missing value sits at the training mean, so it explains nothing.
    assert contributions["b"] == 0.0
    assert RidgeModel.from_json(model.to_json()) == model


def test_ridge_penalty_shrinks_coefficients():
    random = Random(5)
    rows = [{"a": random.gauss(0, 1)} for _ in range(200)]
    targets = [row["a"] + random.gauss(0, 1) for row in rows]
    problem = ridge_module.prepare(("a",), rows, targets, [1.0] * len(rows))

    assert abs(problem.solve(300.0).coefficients[0]) < abs(problem.solve(1.0).coefficients[0])


def test_features_never_see_the_future():
    appearances, fixtures = _league(seasons=1)
    rows = build_rows(appearances, fixtures)
    target_player = "team-0-0"
    cutoff = START + timedelta(days=7 * 10)
    before = {
        row.as_of: row.features
        for row in rows
        if row.provider_player_id == target_player and row.as_of <= cutoff
    }
    assert before

    rewritten = [
        replace(item, rating=1.0, goals=3.0) if item.kickoff_at > cutoff else item
        for item in appearances
    ]
    after = {
        row.as_of: row.features
        for row in build_rows(rewritten, fixtures)
        if row.provider_player_id == target_player and row.as_of <= cutoff
    }
    assert {as_of: after.get(as_of) for as_of in before} == before


def test_targets_are_the_next_appearances_against_the_baseline():
    appearances, fixtures = _league(seasons=1)
    history = sorted(
        (item for item in appearances if item.provider_player_id == "team-1-2"),
        key=lambda item: item.kickoff_at,
    )
    row = next(
        row
        for row in build_rows(appearances, fixtures)
        if row.provider_player_id == "team-1-2" and row.as_of == history[9].kickoff_at
    )

    assert set(row.features[1]) == set(FEATURE_NAMES)
    assert row.targets[1].change == pytest.approx(history[10].rating - row.baseline)
    assert row.targets[5].change == pytest.approx(
        sum(item.rating for item in history[10:15]) / 5 - row.baseline
    )
    assert row.targets[5].matured_at == history[14].kickoff_at
    # The last appearances of the data have no future to learn from.
    assert all(
        other.as_of < history[-1].kickoff_at
        for other in build_rows(appearances, fixtures)
        if other.provider_player_id == "team-1-2"
    )


def test_live_rows_describe_each_player_now_without_targets():
    appearances, fixtures = _league(seasons=1)
    now = START + timedelta(days=7 * 12 + 2)
    rows = build_rows(appearances, fixtures, live_as_of=now, live_season=2024)

    assert len(rows) == len({item.provider_player_id for item in appearances})
    assert all(not row.targets and row.as_of == now for row in rows)


def test_training_beats_the_baseline_when_form_persists():
    appearances, fixtures = _league(seasons=2)
    results = train(build_rows(appearances, fixtures))

    assert results[1].holdout_season == 2025
    assert results[1].training_rows >= MIN_TRAINING_ROWS
    assert results[1].usable and results[1].skill > 0.02
    assert results[1].rank_correlation > 0.1
    promote, reason = promotion_decision(results, None)
    assert promote and "beat the baseline" in reason


def test_promotion_needs_a_usable_horizon_and_no_regression():
    model = RidgeModel(("a",), (0.0,), (1.0,), (0.0,), 0.0, 1.0)
    worse = {1: HorizonResult(1, model, 2000, 2025, 500, 0.8, 0.81, -0.02, 0.0)}
    better = {1: HorizonResult(1, model, 2000, 2025, 500, 0.8, 0.79, 0.02, 0.1)}

    assert promotion_decision(worse, None)[0] is False
    assert promotion_decision(better, None)[0] is True
    active = {"1": {"skill": 0.05, "usable": True}}
    assert promotion_decision(better, active)[0] is False
    assert promotion_decision(better, {"1": {"skill": 0.025, "usable": True}})[0] is True


class _MemoryRepository:
    def __init__(self, history: MatchHistory) -> None:
        self.history = history
        self.models: list[tuple[UUID, bool, dict[int, HorizonResult], datetime]] = []
        self.forecasts: list = []

    def load_history(self) -> MatchHistory:
        return self.history

    def active_model(self) -> StoredModel | None:
        for model_id, promoted, results, trained_at in reversed(self.models):
            if promoted:
                return StoredModel(
                    id=model_id,
                    trained_at=trained_at,
                    models={h: r.model for h, r in results.items() if r.usable},
                    evaluation={str(h): r.evaluation() for h, r in results.items()},
                )
        return None

    def save_model(self, results, *, promote, reason, trained_at, trained_through) -> UUID:
        model_id = uuid4()
        self.models.append((model_id, promote, dict(results), trained_at))
        return model_id

    def save_forecasts(self, model_id, as_of, forecasts) -> int:
        self.forecasts = list(forecasts)
        return len(forecasts)


def test_refresh_trains_once_then_forecasts_only_usable_horizons_for_known_players():
    appearances, fixtures = _league(seasons=2)
    # One player has no canonical identity, so there is no instrument to forecast for.
    appearances = [
        replace(item, player_id=None) if item.provider_player_id == "team-0-0" else item
        for item in appearances
    ]
    repository = _MemoryRepository(MatchHistory(appearances, fixtures, {}, {}))
    now = max(item.kickoff_at for item in appearances) + timedelta(days=1)
    service = ForecastService(repository, clock=lambda: now)

    summary = service.refresh()

    assert summary["status"] == "ok" and summary["training"]["promoted"] is True
    usable = set(repository.active_model().models)
    assert usable and {item.horizon_matches for item in repository.forecasts} == usable
    players = {item.provider_player_id for item in repository.forecasts}
    assert "team-0-0" not in players and len(players) == len(TEAMS) * 14 - 1
    assert all(abs(item.predicted - item.baseline) <= 1.0 for item in repository.forecasts)

    # The model is fresh, so a second run forecasts without training again.
    assert "training" not in service.refresh()
    assert len(repository.models) == 1


def test_refresh_reports_when_no_model_has_earned_its_place():
    appearances, fixtures = _league(seasons=1)
    repository = _MemoryRepository(MatchHistory(appearances[:200], fixtures, {}, {}))
    service = ForecastService(repository, clock=lambda: START + timedelta(days=400))

    assert service.refresh()["status"] == "no_active_model"
    assert repository.forecasts == []


def _forecast_payload(key: str = "FORECAST_FORM_RUN") -> dict:
    return next(
        payload
        for config_key, _, payload in _migration_profiles("0042_player_forecasts.sql")
        if config_key == key
    )


def test_seeded_forecast_profiles_parse_and_keep_their_horizon_when_randomized():
    profiles = _migration_profiles("0042_player_forecasts.sql")
    assert {key: payload["forecast_inputs"]["horizon_matches"] for key, _, payload in profiles} == {
        "FORECAST_NEXT_MATCH": 1,
        "FORECAST_FORM_RUN": 5,
        "FORECAST_SEASON_VIEW": 10,
    }
    random_source = Random(20261114)
    for config_key, engine, payload in profiles:
        assert engine is StrategyEngine.FORECAST_VALUE
        for _ in range(50):
            overrides = build_random_config_overrides(
                config_key=config_key,
                strategy_engine=engine,
                base_config=payload,
                random_source=random_source,
            )
            config = parse_strategy_config(engine, apply_config_overrides(payload, overrides))
            assert (
                config.forecast_inputs.horizon_matches
                == payload["forecast_inputs"]["horizon_matches"]
            )


def _bot(as_of: datetime) -> SyntheticTraderBotRecord:
    return SyntheticTraderBotRecord(
        id=uuid4(),
        account_id=uuid4(),
        portfolio_id=uuid4(),
        config_id=uuid4(),
        bot_key="forecast-bot",
        display_name="Forecast Bot",
        status=BotStatus.ACTIVE,
        config_overrides={},
        last_ticked_at=None,
        next_tick_after=None,
        created_at=as_of,
        updated_at=as_of,
    )


def test_forecast_engine_buys_expected_improvers_and_sells_held_decliners():
    as_of = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    config = parse_strategy_config(StrategyEngine.FORECAST_VALUE, _forecast_payload())

    def forecast(change: float, *, hours_old: float = 2.0, horizon: int = 5):
        return PlayerForecastContext(
            as_of=as_of - timedelta(hours=hours_old),
            baseline_rating=7.0,
            history_nineties=20.0,
            expected_change={horizon: change},
        )

    flat_prices = (Decimal("20"), Decimal("20"), Decimal("20"))
    improver = replace(_candidate(recent_price_values=flat_prices), forecast=forecast(0.15))
    decliner = replace(
        _candidate(recent_price_values=flat_prices, holding_quantity=Decimal("5")),
        forecast=forecast(-0.15),
    )
    unheld_decliner = replace(_candidate(recent_price_values=flat_prices), forecast=forecast(-0.2))
    steady = replace(_candidate(recent_price_values=flat_prices), forecast=forecast(0.0))
    stale = replace(
        _candidate(recent_price_values=flat_prices), forecast=forecast(0.3, hours_old=24 * 30)
    )
    other_horizon = replace(
        _candidate(recent_price_values=flat_prices), forecast=forecast(0.3, horizon=1)
    )
    unforecast = _candidate(recent_price_values=flat_prices)

    decisions = {
        decision.instrument_id: decision
        for decision in ForecastValueStrategyEngine().evaluate(
            _context(
                _bot(as_of),
                candidates=(
                    improver,
                    decliner,
                    unheld_decliner,
                    steady,
                    stale,
                    other_horizon,
                    unforecast,
                ),
            ),
            config,
        )
    }

    assert decisions[improver.instrument_id].side is DecisionSide.BUY
    assert decisions[decliner.instrument_id].side is DecisionSide.SELL
    # Long-only: a decline in a player the bot does not hold is nothing to act on.
    assert decisions[unheld_decliner.instrument_id].side is DecisionSide.HOLD
    assert decisions[steady.instrument_id].side is DecisionSide.HOLD
    for ignored in (stale, other_horizon, unforecast):
        assert ignored.instrument_id not in decisions
    reason = decisions[improver.instrument_id].reason
    assert reason["horizon_matches"] == 5 and reason["expected_change"] == pytest.approx(0.15)


def test_forecast_engine_treats_a_price_that_already_rose_as_priced_in():
    as_of = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    config = parse_strategy_config(StrategyEngine.FORECAST_VALUE, _forecast_payload())
    forecast = PlayerForecastContext(
        as_of=as_of - timedelta(hours=1),
        baseline_rating=7.0,
        history_nineties=20.0,
        expected_change={5: 0.15},
    )
    flat = replace(
        _candidate(recent_price_values=(Decimal("20"), Decimal("20"), Decimal("20"))),
        forecast=forecast,
    )
    risen = replace(
        _candidate(recent_price_values=(Decimal("16"), Decimal("18"), Decimal("20"))),
        forecast=forecast,
    )
    decisions = {
        decision.instrument_id: decision
        for decision in ForecastValueStrategyEngine().evaluate(
            _context(_bot(as_of), candidates=(flat, risen)), config
        )
    }

    assert decisions[risen.instrument_id].alpha_score < decisions[flat.instrument_id].alpha_score


def test_fotmob_job_refreshes_forecasts_without_letting_them_fail_the_ingestion():
    service = Mock()
    service.ingest.return_value = {"upserted_observations": 22, "failed_matches": 0}
    job = WorkerJob(JobType.INGEST_FOTMOB_RATINGS, {"season": 2025})

    refreshed = FotMobRatingsJobHandler(
        lambda: service, refresh_forecasts=lambda: {"status": "ok", "forecasts": 3}
    ).handle(job)
    assert refreshed.metrics["forecasts"] == {"status": "ok", "forecasts": 3}

    def broken() -> dict:
        raise RuntimeError("no model table")

    failed = FotMobRatingsJobHandler(lambda: service, refresh_forecasts=broken).handle(job)
    assert failed.successful_items == 22 and failed.retryable_failures == 0
    assert failed.metrics["forecasts"]["status"] == "failed"

    service.ingest.return_value = {"upserted_observations": 0, "failed_matches": 0}
    untouched = Mock()
    FotMobRatingsJobHandler(lambda: service, refresh_forecasts=untouched).handle(job)
    untouched.assert_not_called()


ODDS_CSV = """﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,AvgH,AvgD,AvgA,B365H,B365D,B365A
E0,16/08/2025,15:00,Man United,Wolves,2,0,1.50,4.20,7.00,1.5,4.2,7
E0,16/08/2025,15:00,Man City,Nott'm Forest,1,1,,,,1.30,5.50,10.00
E0,17/08/25,14:00,Brighton,Fulham,0,0,2.00,3.40,3.80,2,3.4,3.8
E0,17/08/2025,16:30,Leeds,Everton,0,0,,,,,,
"""


def test_match_odds_parse_to_margin_free_probabilities():
    from app.forecasting.odds import parse_match_odds, season_url

    rows = parse_match_odds(ODDS_CSV)

    # The row with no prices is skipped; one without the market average uses a bookmaker.
    assert [row.home_team for row in rows] == ["Man United", "Man City", "Brighton"]
    united = rows[0]
    assert united.home_probability + united.draw_probability + united.away_probability == (
        pytest.approx(1.0)
    )
    assert united.home_probability > 0.6 > united.away_probability
    assert rows[2].match_date.isoformat() == "2025-08-17"
    assert season_url(2025).endswith("/2526/E0.csv")


def test_match_odds_link_to_the_right_fixture_despite_shared_first_words():
    from app.forecasting.odds import _match, parse_match_odds

    kickoff = datetime(2025, 8, 16, 14, 0, tzinfo=UTC)
    fixtures = [
        {"match_id": "1", "kickoff_at": kickoff, "home_team_name": "Manchester City",
         "away_team_name": "Nottingham Forest"},
        {"match_id": "2", "kickoff_at": kickoff, "home_team_name": "Manchester United",
         "away_team_name": "Wolverhampton Wanderers"},
        # Kicked off just after midnight UTC on the source's date.
        {"match_id": "3", "kickoff_at": datetime(2025, 8, 18, 0, 30, tzinfo=UTC),
         "home_team_name": "Brighton & Hove Albion", "away_team_name": "Fulham"},
    ]
    by_date: dict = {}
    for fixture in fixtures:
        by_date.setdefault(fixture["kickoff_at"].date(), []).append(fixture)
    united, city, brighton = parse_match_odds(ODDS_CSV)

    assert _match(united, by_date) == "2"
    assert _match(city, by_date) == "1"
    assert _match(brighton, by_date) == "3"
    assert _match(replace(brighton, home_team="Burnley"), by_date) is None


def test_team_strength_follows_recent_odds_and_never_later_ones():
    from app.forecasting.features import LeagueContext

    fixtures = [
        Fixture(f"m{index}", 2025, START + timedelta(days=7 * index), "strong", "weak", True,
                2, 0, home_edge=0.5)
        for index in range(6)
    ]
    context = LeagueContext(fixtures)
    midway = START + timedelta(days=7 * 2)

    assert context.strength("strong", midway) == pytest.approx(1.5 / 6.0)
    assert context.strength("weak", midway) == pytest.approx(-1.5 / 6.0)
    assert context.strength("strong", START - timedelta(days=1)) is None
    assert [fixture.match_id for fixture in context.upcoming("weak", midway, 2)] == ["m3", "m4"]
    # A fixture list with no odds at all leaves the feature empty rather than zero.
    assert LeagueContext([replace(f, home_edge=None) for f in fixtures]).strength(
        "strong", midway
    ) is None
