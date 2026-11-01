from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.index_funds import IndexReviewService, ReviewAction, RuleFund
from app.index_funds.rules import (
    LAUNCH_UNIT_PRICE,
    RULE_FUNDS,
    LeagueFacts,
    Metric,
    PlayerFacts,
    RuleFundDefinition,
    Weighting,
    definition_for,
    launch_basket,
    select_members,
    value_drift,
)
from tests.test_index_funds import FakeFundEngine, FakeFundRepository

NOW = datetime(2026, 10, 31, 6, tzinfo=UTC)


def _player(**facts) -> PlayerFacts:
    facts.setdefault("instrument_id", uuid4())
    facts.setdefault("club", "Arsenal")
    facts.setdefault("price", Decimal("20"))
    return PlayerFacts(**facts)


def _league(*players: PlayerFacts, previous: frozenset[str] = frozenset()) -> LeagueFacts:
    return LeagueFacts(season=2026, players=players, previous_season_clubs=previous)


def _valued(count: int, **facts) -> list[PlayerFacts]:
    """Players valued 1000, 999, ... so rank n is index n - 1."""
    return [_player(valuation=float(1000 - n), **facts) for n in range(count)]


def _ranked(size: int, buffer: int = 0, **changes) -> RuleFundDefinition:
    return RuleFundDefinition(
        key="TEST", symbol="IDX-TST", name="Test", category="Market", description="Test",
        rank_by=Metric.VALUATION, size=size, buffer=buffer, min_members=1, **changes,
    )


class RuleDefinitionTests(unittest.TestCase):
    def test_twenty_funds_with_unique_keys_and_symbols(self) -> None:
        self.assertEqual(len(RULE_FUNDS), 20)
        self.assertEqual(len({d.key for d in RULE_FUNDS}), 20)
        self.assertEqual(len({d.symbol for d in RULE_FUNDS}), 20)
        for definition in RULE_FUNDS:
            self.assertTrue(definition.symbol.startswith("IDX-"))
            self.assertLessEqual(len(definition.name), 24)

    def test_stored_rule_leaves_out_unset_conditions(self) -> None:
        rule = definition_for("UNDER_21").rule()
        self.assertEqual(rule["eligibility"], {"max_age": 21, "min_minutes_share": 0.5})
        self.assertEqual(rule["rank_by"], "VALUATION")
        self.assertEqual(rule["weighting"], "EQUAL_VALUE")
        self.assertNotIn("name", rule)
        self.assertEqual(
            definition_for("SOUTH_AMERICA").rule()["eligibility"]["nationalities"][:2],
            ["ARG", "BOL"],
        )


class SelectionTests(unittest.TestCase):
    def test_takes_the_top_of_the_ranking(self) -> None:
        players = _valued(30)
        selected = select_members(_ranked(20), _league(*players))
        self.assertEqual(set(selected), {p.instrument_id for p in players[:20]})

    def test_window_from_a_later_rank(self) -> None:
        players = _valued(30)
        definition = _ranked(10, rank_from=11)
        selected = select_members(definition, _league(*players))
        self.assertEqual(set(selected), {p.instrument_id for p in players[10:20]})

    def test_buffer_keeps_members_near_the_cut_off_and_holds_back_newcomers(self) -> None:
        players = _valued(30)
        ids = [p.instrument_id for p in players]
        # Ranks 1-19 and 22 are members; 20 and 21 are not.
        current = frozenset(ids[:19] + [ids[21]])
        selected = set(select_members(_ranked(20, buffer=2), _league(*players), current))
        self.assertEqual(selected, set(current))

        # A member that falls past the buffer is replaced by the best non-member.
        current = frozenset(ids[:19] + [ids[24]])
        selected = set(select_members(_ranked(20, buffer=2), _league(*players), current))
        self.assertEqual(selected, set(ids[:20]))

    def test_newcomers_well_inside_the_cut_off_displace_the_worst_member(self) -> None:
        players = _valued(30)
        ids = [p.instrument_id for p in players]
        # Members are ranks 2-21; rank 1 is new and must join, so rank 21 leaves.
        current = frozenset(ids[1:21])
        selected = set(select_members(_ranked(20, buffer=2), _league(*players), current))
        self.assertEqual(selected, set(ids[:20]))

    def test_eligibility_filters(self) -> None:
        striker = _player(position="FW", valuation=50.0)
        midfielder = _player(position="MF", valuation=90.0)
        young = _player(age=19, games=10, minutes=500, valuation=10.0)
        unused_youngster = _player(age=19, games=3, minutes=100, valuation=99.0)
        veteran = _player(age=33, games=10, minutes=900, valuation=5.0)
        brazilian = _player(nationality="BRA")
        english = _player(nationality="ENG")
        league = _league(
            striker, midfielder, young, unused_youngster, veteran, brazilian, english
        )

        forwards = replace(definition_for("FORWARDS"), min_members=1)
        self.assertEqual(select_members(forwards, league), (striker.instrument_id,))
        wonderkids = definition_for("UNDER_21")
        self.assertEqual(select_members(wonderkids, league), (young.instrument_id,))
        self.assertEqual(
            select_members(definition_for("OVER_32"), league), (veteran.instrument_id,)
        )
        self.assertEqual(
            select_members(definition_for("SOUTH_AMERICA"), league), (brazilian.instrument_id,)
        )

    def test_club_groups_and_promoted_clubs(self) -> None:
        arsenal = _player(club="Arsenal")
        palace = _player(club="Crystal Palace")
        coventry = _player(club="Coventry City")
        everton = _player(club="Everton")
        league = _league(
            arsenal, palace, coventry, everton,
            previous=frozenset({"Arsenal", "Crystal Palace", "Everton", "Burnley"}),
        )
        self.assertEqual(
            set(select_members(definition_for("BIG6"), league)), {arsenal.instrument_id}
        )
        self.assertEqual(
            set(select_members(definition_for("LONDON"), league)),
            {arsenal.instrument_id, palace.instrument_id},
        )
        self.assertEqual(
            select_members(definition_for("PROMOTED"), league), (coventry.instrument_id,)
        )
        # Without last season's data, no club counts as promoted.
        self.assertEqual(select_members(definition_for("PROMOTED"), _league(coventry)), ())

    def test_first_choice_keeper_per_club(self) -> None:
        starter = _player(position="GK", keeper_minutes=630)
        backup = _player(position="GK", keeper_minutes=90, valuation=99.0)
        other_club = _player(club="Everton", position="GK", keeper_minutes=0)
        outfield = _player(position="DF", keeper_minutes=900)
        selected = select_members(
            definition_for("KEEPERS"), _league(starter, backup, other_club, outfield)
        )
        self.assertEqual(set(selected), {starter.instrument_id, other_club.instrument_id})

    def test_iron_men_play_nearly_every_minute(self) -> None:
        ever_present = _player(games=7, minutes=630)
        nearly = _player(games=7, minutes=570)
        rotated = _player(games=6, minutes=400)
        iron_men = replace(definition_for("IRON_MEN"), min_members=1)
        selected = select_members(iron_men, _league(ever_present, nearly, rotated))
        self.assertEqual(set(selected), {ever_present.instrument_id, nearly.instrument_id})

    def test_performance_and_signal_metrics_skip_players_without_data(self) -> None:
        scorer = _player(non_penalty_goals=6, minutes=600)
        quicker = _player(non_penalty_goals=6, minutes=500)
        blank = _player(non_penalty_goals=0, minutes=900)
        golden = replace(definition_for("GOLDEN_BOOT"), size=2, min_members=1)
        self.assertEqual(
            set(select_members(golden, _league(scorer, quicker, blank))),
            {scorer.instrument_id, quicker.instrument_id},
        )
        top_one = replace(golden, size=1, buffer=0)
        self.assertEqual(
            select_members(top_one, _league(scorer, quicker, blank)), (quicker.instrument_id,)
        )

        priced = _player(goalscorer_probability=0.4)
        unpriced = _player()
        bookies = replace(definition_for("BOOKIES"), min_members=1)
        self.assertEqual(
            select_members(bookies, _league(priced, unpriced)), (priced.instrument_id,)
        )

        loved = _player(social_mentions=40, social_sentiment=0.5)
        hated = _player(social_mentions=100, social_sentiment=-1.0)
        quiet = _player(social_mentions=10, social_sentiment=0.0)
        buzz = replace(definition_for("BUZZ"), size=2, buffer=0, min_members=1)
        self.assertEqual(
            set(select_members(buzz, _league(loved, hated, quiet))),
            {loved.instrument_id, quiet.instrument_id},
        )

    def test_creators_rank_chances_per_90(self) -> None:
        creator = _player(chances_created=22, games=20, minutes=900)
        volume = _player(chances_created=28, games=20, minutes=1800)
        short = _player(chances_created=11, games=20, minutes=300)
        creators = replace(definition_for("CREATORS"), size=1, buffer=0, min_members=1)
        self.assertEqual(
            select_members(creators, _league(creator, volume, short)), (creator.instrument_id,)
        )


class LaunchBasketTests(unittest.TestCase):
    def test_lists_at_the_launch_price_by_weighting(self) -> None:
        cheap, dear = uuid4(), uuid4()
        prices = {cheap: Decimal("10"), dear: Decimal("40")}

        shares = dict(launch_basket(_ranked(2), (cheap, dear), prices))
        self.assertEqual(shares[cheap], shares[dear])
        self.assertAlmostEqual(
            float(sum(Decimal(shares[i]) * prices[i] for i in prices)),
            float(LAUNCH_UNIT_PRICE), places=3,
        )

        equal_value = _ranked(2, weighting=Weighting.EQUAL_VALUE)
        shares = dict(launch_basket(equal_value, (cheap, dear), prices))
        self.assertEqual(shares, {cheap: "5.000000", dear: "1.250000"})

    def test_value_drift(self) -> None:
        a, b = uuid4(), uuid4()
        self.assertEqual(value_drift({a: (Decimal(1), Decimal(10)), b: (Decimal(2), Decimal(5))}), 0)
        self.assertAlmostEqual(
            value_drift({a: (Decimal(1), Decimal(30)), b: (Decimal(1), Decimal(10))}), 0.5
        )


def _rule_fund(definition: RuleFundDefinition, members, **changes) -> RuleFund:
    fields = dict(
        instrument_id=uuid4(),
        symbol=definition.symbol,
        rule_key=definition.key,
        members=frozenset(members),
        unit_price="100",
        holdings={member: (Decimal("1"), Decimal("20")) for member in members},
        last_rebalanced_at=NOW - timedelta(days=40),
    )
    fields.update(changes)
    return RuleFund(**fields)


def _service(repository, engine, *definitions) -> IndexReviewService:
    return IndexReviewService(repository, engine, definitions=definitions, clock=lambda: NOW)


class RuleReviewTests(unittest.TestCase):
    def test_lists_rule_funds_with_enough_players(self) -> None:
        players = _valued(25)
        small = replace(_ranked(20), key="SMALL", symbol="IDX-SML", min_members=30)
        engine = FakeFundEngine()

        result = _service(
            FakeFundRepository([], league=_league(*players)), engine, _ranked(20), small
        ).review(2026)

        (created,) = engine.created
        self.assertEqual(created.symbol, "IDX-TST")
        self.assertEqual(created.index_kind, "RULE")
        self.assertIsNone(created.club)
        self.assertEqual(created.rule_key, "TEST")
        self.assertEqual(created.category, "Market")
        self.assertEqual(created.rule["rank_by"], "VALUATION")
        self.assertEqual(created.weighting, "EQUAL_SHARES")
        self.assertEqual(len(created.constituents), 20)
        self.assertEqual(result.count(ReviewAction.CREATED), 1)
        self.assertEqual(result.rules_too_small, {"IDX-SML": 20})
        payload = created.to_payload()
        self.assertEqual(payload["rule_key"], "TEST")
        self.assertEqual(payload["weighting"], "EQUAL_SHARES")

    def test_rebalances_only_when_the_review_is_due(self) -> None:
        players = _valued(25)
        definition = _ranked(20, review_days=30)
        stale = frozenset(p.instrument_id for p in players[5:25])
        engine = FakeFundEngine()

        recent = _rule_fund(definition, stale, last_rebalanced_at=NOW - timedelta(days=3))
        result = _service(
            FakeFundRepository([], league=_league(*players), rule_funds=[recent]),
            engine, definition,
        ).review(2026)
        self.assertEqual(result.reviews[0].action, ReviewAction.UNCHANGED)
        self.assertEqual(engine.rebalanced, [])

        due = _rule_fund(definition, stale)
        result = _service(
            FakeFundRepository([], league=_league(*players), rule_funds=[due]),
            engine, definition,
        ).review(2026)
        (review,) = result.reviews
        self.assertEqual(review.action, ReviewAction.REBALANCED)
        self.assertEqual(set(review.added), {p.instrument_id for p in players[:5]})
        (command,) = engine.rebalanced
        self.assertEqual(set(command.members), {p.instrument_id for p in players[:20]})
        self.assertTrue(command.reason.startswith("rule result changed"))

    def test_keeps_the_basket_when_too_few_players_qualify(self) -> None:
        definition = replace(definition_for("BOOKIES"), review_days=7)
        members = [uuid4() for _ in range(15)]
        fund = _rule_fund(definition, members)
        engine = FakeFundEngine()
        # The odds feed has stopped: nobody has a fresh price.
        result = _service(
            FakeFundRepository([], league=_league(*_valued(30)), rule_funds=[fund]),
            engine, definition,
        ).review(2026)
        self.assertEqual(result.reviews[0].action, ReviewAction.UNCHANGED)
        self.assertEqual(engine.rebalanced, [])

    def test_relevels_equal_value_funds_that_drift(self) -> None:
        players = _valued(20)
        definition = _ranked(20, weighting=Weighting.EQUAL_VALUE, review_days=7)
        members = [p.instrument_id for p in players]
        holdings = {member: (Decimal("1"), Decimal("5")) for member in members}
        holdings[members[0]] = (Decimal("1"), Decimal("20"))
        fund = _rule_fund(definition, members, holdings=holdings)
        engine = FakeFundEngine()

        result = _service(
            FakeFundRepository([], league=_league(*players), rule_funds=[fund]),
            engine, definition,
        ).review(2026)

        self.assertEqual(result.reviews[0].action, ReviewAction.REBALANCED)
        self.assertEqual(engine.rebalanced[0].reason, "re-levelling member weights")

    def test_keeps_members_waiting_for_their_buyout(self) -> None:
        players = _valued(20)
        definition = _ranked(20)
        departed = uuid4()
        members = {p.instrument_id for p in players} | {departed}
        fund = _rule_fund(definition, members, halted_members=frozenset({departed}))
        engine = FakeFundEngine()

        result = _service(
            FakeFundRepository([], league=_league(*players), rule_funds=[fund]),
            engine, definition,
        ).review(2026)

        self.assertEqual(result.reviews[0].action, ReviewAction.UNCHANGED)
        self.assertIn(departed, fund.members)


if __name__ == "__main__":
    unittest.main()
