from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

from app.clients import (
    CreateIndexFundRecord,
    RebalanceIndexFundRecord,
    TradingEngineClientError,
)
from app.index_funds import (
    MIN_TEAM_PLAYERS,
    IndexReviewService,
    ReviewAction,
    TeamFund,
    TeamRoster,
    club_code,
    team_fund_symbol,
)
from app.synthetic_traders import (
    BotActivityContext,
    BotPortfolioContext,
    CandidateInstrumentContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
    SyntheticTraderBotConfigRecord,
    SyntheticTraderService,
    parse_strategy_config,
)
from app.synthetic_traders.fund_decisions import index_fund_decisions
from tests.test_synthetic_trader_configs import _stats_value_payload
from tests.test_synthetic_trader_engines import _candidate
from tests.test_synthetic_trader_service import (
    FakeSyntheticTraderRepository,
    FakeTradingEngineClient,
    StubEngine,
    SyntheticTraderServiceTests,
    _noise_payload,
)


def _fund(
    players: tuple[CandidateInstrumentContext, ...],
    *,
    holding: Decimal = Decimal("0"),
    trading_status: str = "ACTIVE",
) -> CandidateInstrumentContext:
    base = _candidate(club="Arsenal", position=None, current_price=Decimal("100"))
    return replace(
        base,
        player_id=None,
        symbol="IDX-ARS",
        display_name="Arsenal Index",
        trading_status=trading_status,
        current_holding_quantity=holding,
        index_basket=tuple((player.instrument_id, Decimal("1")) for player in players),
    )


def _decision(instrument_id: UUID, alpha: float, confidence: float = 0.8) -> StrategyDecision:
    return StrategyDecision(
        instrument_id=instrument_id,
        side=DecisionSide.BUY if alpha > 0 else DecisionSide.HOLD,
        alpha_score=alpha,
        expected_return=alpha / 10,
        confidence=confidence,
        suggested_cash_pct=0.05,
        reason={},
    )


class IndexFundDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())
        self.players = tuple(
            _candidate(current_price=price)
            for price in (Decimal("60"), Decimal("20"), Decimal("10"), Decimal("10"))
        )

    def decide(self, fund, decisions):
        return index_fund_decisions(
            (*self.players, fund), decisions, self.config.decision, self.config.universe
        )

    def test_weights_each_player_by_its_share_of_the_unit_price(self) -> None:
        fund = _fund(self.players)
        alphas = (0.9, 0.3, -0.3, -0.3)
        decisions = tuple(
            _decision(player.instrument_id, alpha)
            for player, alpha in zip(self.players, alphas, strict=True)
        )

        (fund_decision,) = self.decide(fund, decisions)

        # (60 x 0.9 + 20 x 0.3 - 10 x 0.3 - 10 x 0.3) / 100
        self.assertAlmostEqual(fund_decision.alpha_score, 0.54)
        self.assertEqual(fund_decision.instrument_id, fund.instrument_id)
        self.assertEqual(fund_decision.side, DecisionSide.HOLD)
        self.assertEqual(fund_decision.reason["scored_constituents"], 4)

    def test_buys_when_the_engine_likes_most_of_the_squad(self) -> None:
        fund = _fund(self.players)
        decisions = tuple(_decision(player.instrument_id, 0.8) for player in self.players)

        (fund_decision,) = self.decide(fund, decisions)

        self.assertEqual(fund_decision.side, DecisionSide.BUY)

    def test_needs_enough_scored_players(self) -> None:
        fund = _fund(self.players)
        decisions = tuple(_decision(player.instrument_id, 0.8) for player in self.players[:2])

        self.assertEqual(self.decide(fund, decisions), ())

    def test_sells_only_a_fund_it_holds(self) -> None:
        decisions = tuple(_decision(player.instrument_id, -0.9) for player in self.players)

        (unheld,) = self.decide(_fund(self.players), decisions)
        (held,) = self.decide(_fund(self.players, holding=Decimal("2")), decisions)

        self.assertEqual(unheld.side, DecisionSide.HOLD)
        self.assertEqual(held.side, DecisionSide.SELL)

    def test_skips_a_paused_fund(self) -> None:
        decisions = tuple(_decision(player.instrument_id, 0.8) for player in self.players)

        self.assertEqual(self.decide(_fund(self.players, trading_status="FROZEN"), decisions), ())


class IndexFundTickTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = SyntheticTraderServiceTests()
        fixture.setUp()
        self.as_of = fixture.as_of
        self.bot = fixture.bot
        self.players = tuple(_candidate(current_price=Decimal("20")) for _ in range(3))
        self.fund = _fund(self.players)

    def tick(self, strategy_engine: StrategyEngine, payload, engine: StubEngine):
        repository = FakeSyntheticTraderRepository(
            bot=self.bot,
            config=SyntheticTraderBotConfigRecord(
                id=self.bot.config_id,
                config_key="TEST",
                display_name="Test",
                strategy_engine=strategy_engine,
                version=1,
                config=payload,
                enabled=True,
                created_at=self.as_of,
                updated_at=self.as_of,
            ),
            portfolio=BotPortfolioContext(
                account_id=self.bot.account_id,
                portfolio_id=self.bot.portfolio_id,
                cash_balance=Decimal("100000"),
                total_position_value=Decimal("0"),
                total_equity=Decimal("100000"),
                positions=(),
            ),
            activity=BotActivityContext(
                daily_trade_count=0, daily_turnover_cash=Decimal("0"), last_order_at=None
            ),
            candidates=(*self.players, self.fund),
        )
        client = FakeTradingEngineClient(repository.portfolio)
        service = SyntheticTraderService(
            repository=repository,
            trading_engine_client=client,
            engine_registry={strategy_engine: engine},
        )
        service.tick_due_bots(self.as_of, force_timing=True)
        return client

    def test_fundamentals_engines_buy_a_fund_through_its_players(self) -> None:
        payload = _stats_value_payload()
        payload["execution"] = {**payload["execution"], "trade_probability": 1.0}
        engine = StubEngine(
            tuple(
                replace(_decision(player.instrument_id, 0.9), side=DecisionSide.HOLD)
                for player in self.players
            )
        )

        client = self.tick(StrategyEngine.STATS_VALUE, payload, engine)

        candidate_ids = {candidate.instrument_id for candidate in engine.calls[0].candidates}
        self.assertNotIn(self.fund.instrument_id, candidate_ids)
        self.assertEqual(
            [command.instrument_id for command in client.commands], [self.fund.instrument_id]
        )

    def test_market_data_engines_see_funds_as_candidates(self) -> None:
        engine = StubEngine(())
        self.tick(StrategyEngine.NOISE, _noise_payload(), engine)

        candidate_ids = {candidate.instrument_id for candidate in engine.calls[0].candidates}
        self.assertIn(self.fund.instrument_id, candidate_ids)


class FakeFundRepository:
    def __init__(self, rosters: list[TeamRoster], funds: list[TeamFund] | None = None):
        self.rosters = rosters
        self.funds = funds or []

    def team_rosters(self, season: int) -> list[TeamRoster]:
        return self.rosters

    def team_funds(self) -> list[TeamFund]:
        return self.funds


class FakeFundEngine:
    def __init__(self, failing_symbols: set[str] | None = None, fail_rebalances: bool = False):
        self.created = []
        self.rebalanced = []
        self.failing_symbols = failing_symbols or set()
        self.fail_rebalances = fail_rebalances

    def create_index_fund(self, command):
        self.created.append(command)
        if command.symbol in self.failing_symbols:
            raise TradingEngineClientError(409, {"code": "conflict", "message": "taken"})
        return CreateIndexFundRecord(
            instrument_id=uuid4(),
            symbol=command.symbol,
            created=True,
            constituent_count=len(command.constituents),
            unit_price="250.0",
        )

    def rebalance_index_fund(self, command):
        self.rebalanced.append(command)
        if self.fail_rebalances:
            raise TradingEngineClientError(409, {"code": "instrument_frozen", "message": "paused"})
        return RebalanceIndexFundRecord(
            rebalance_id=uuid4(),
            instrument_id=command.instrument_id,
            replayed=False,
            units_outstanding="2",
            unit_price_before="250.0",
            unit_price_after="249.9",
            cash_per_unit_after="0",
            added_instrument_ids=(),
            removed_instrument_ids=(),
        )


def _roster(club: str, size: int = MIN_TEAM_PLAYERS) -> TeamRoster:
    return TeamRoster(club, tuple(uuid4() for _ in range(size)))


def _team_fund(roster: TeamRoster, *, halted: frozenset[UUID] = frozenset()) -> TeamFund:
    return TeamFund(
        instrument_id=uuid4(),
        symbol=f"IDX-{roster.club[:3].upper()}",
        club=roster.club,
        members=frozenset(roster.instrument_ids) | halted,
        halted_members=halted,
    )


class IndexReviewServiceTests(unittest.TestCase):
    def test_lists_a_fund_per_club_with_one_share_of_each_player(self) -> None:
        engine = FakeFundEngine()
        service = IndexReviewService(
            FakeFundRepository([_roster("Arsenal"), _roster("Manchester Utd", 25)]), engine
        )

        result = service.review(2026)

        self.assertEqual(result.count(ReviewAction.CREATED), 2)
        self.assertEqual([c.symbol for c in engine.created], ["IDX-ARS", "IDX-MUN"])
        manchester = engine.created[1]
        self.assertEqual(manchester.display_name, "Manchester Utd Index")
        self.assertEqual(manchester.index_kind, "TEAM")
        self.assertEqual(manchester.club, "Manchester Utd")
        self.assertEqual(len(manchester.constituents), 25)
        self.assertTrue(all(shares == "1" for _, shares in manchester.constituents))

    def test_rebalances_a_fund_to_its_rule_when_the_squad_changes(self) -> None:
        listed = _roster("Arsenal", 12)
        signing, sold = uuid4(), listed.instrument_ids[0]
        fund = _team_fund(listed)
        today = TeamRoster("Arsenal", (*listed.instrument_ids[1:], signing))
        engine = FakeFundEngine()

        result = IndexReviewService(FakeFundRepository([today], [fund]), engine).review(2026)

        (review,) = result.reviews
        self.assertEqual(review.action, ReviewAction.REBALANCED)
        self.assertEqual((review.added, review.removed), ((signing,), (sold,)))
        (command,) = engine.rebalanced
        self.assertEqual(command.instrument_id, fund.instrument_id)
        self.assertEqual(set(command.members), set(today.instrument_ids))
        # The same target always makes the same request, so a retry replays.
        again = FakeFundEngine()
        IndexReviewService(FakeFundRepository([today], [fund]), again).review(2026)
        self.assertEqual(again.rebalanced[0].request_id, command.request_id)

    def test_keeps_players_waiting_for_their_buyout(self) -> None:
        listed = _roster("Arsenal", 12)
        departed = uuid4()
        fund = _team_fund(listed, halted=frozenset({departed}))
        engine = FakeFundEngine()

        result = IndexReviewService(FakeFundRepository([listed], [fund]), engine).review(2026)

        self.assertEqual(result.reviews[0].action, ReviewAction.UNCHANGED)
        self.assertEqual(engine.rebalanced, [])

    def test_unchanged_dry_run_failure_and_relegation(self) -> None:
        arsenal, chelsea, burnley = _roster("Arsenal"), _roster("Chelsea"), _roster("Burnley")
        funds = [_team_fund(arsenal), _team_fund(chelsea), _team_fund(burnley)]
        moved = TeamRoster("Chelsea", (*chelsea.instrument_ids, uuid4()))
        tiny = _roster("Leeds United", MIN_TEAM_PLAYERS - 1)

        dry = FakeFundEngine()
        dry_result = IndexReviewService(
            FakeFundRepository([arsenal, moved, tiny], funds), dry
        ).review(2026, dry_run=True)
        self.assertEqual(
            {r.club: r.action for r in dry_result.reviews},
            {"Arsenal": ReviewAction.UNCHANGED, "Chelsea": ReviewAction.WOULD_REBALANCE},
        )
        self.assertEqual((dry.created, dry.rebalanced), ([], []))
        self.assertEqual(dry_result.too_small, {"Leeds United": MIN_TEAM_PLAYERS - 1})
        self.assertEqual(dry_result.without_roster, ("Burnley",))

        failing = FakeFundEngine(fail_rebalances=True)
        result = IndexReviewService(FakeFundRepository([moved], funds), failing).review(2026)
        self.assertEqual(result.count(ReviewAction.FAILED), 1)
        self.assertIn("paused", result.reviews[0].error or "")

    def test_reinvests_cash_from_buyouts(self) -> None:
        listed = _roster("Arsenal", 12)
        holding_cash = replace(_team_fund(listed), cash_per_unit="12.5", unit_price="250")
        sliver = replace(_team_fund(listed), cash_per_unit="0.01", unit_price="250")
        engine = FakeFundEngine()

        result = IndexReviewService(FakeFundRepository([listed], [holding_cash]), engine).review(
            2026
        )
        IndexReviewService(FakeFundRepository([listed], [sliver]), engine).review(2026)

        self.assertEqual(result.reviews[0].action, ReviewAction.REBALANCED)
        (command,) = engine.rebalanced
        self.assertEqual(command.reason, "reinvesting cash from buyouts")
        self.assertEqual(set(command.members), set(listed.instrument_ids))

    def test_unknown_clubs_get_distinct_symbols(self) -> None:
        engine = FakeFundEngine()
        IndexReviewService(
            FakeFundRepository([_roster("Riverside Rovers"), _roster("Riverton Albion")]), engine
        ).review(2026)

        self.assertEqual([c.symbol for c in engine.created], ["IDX-RIV", "IDX-RIV2"])


class ClubCodeTests(unittest.TestCase):
    def test_known_and_unknown_clubs(self) -> None:
        self.assertEqual(club_code("Nott'ham Forest"), "NFO")
        self.assertEqual(club_code("Nottingham"), "NFO")
        self.assertEqual(club_code("Newcastle"), "NEW")
        self.assertEqual(club_code("Hull City"), "HUL")
        self.assertEqual(club_code("Brighton & Hove Albion"), "BHA")
        self.assertEqual(club_code("Wolves"), "WOL")
        self.assertEqual(team_fund_symbol("Tottenham"), "IDX-TOT")
        self.assertEqual(club_code("Ipswich"), "IPS")
        self.assertEqual(club_code("Ébbsfleet"), "EBB")
